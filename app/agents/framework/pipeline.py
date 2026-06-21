import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from app.agents.framework.base import BaseAgent
from app.agents.framework.cache import AgentResultCache
from app.agents.framework.events import AgentEventLogger, NullAgentEventLogger
from app.agents.framework.models import (
    AgentContext,
    AgentEvent,
    AgentEventType,
    AgentResult,
    PipelineResult,
    PipelineStatus,
)

if TYPE_CHECKING:
    from app.agents.framework.registry import AgentRegistry


class ExecutionMode(StrEnum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 1
    initial_delay_seconds: float = 0.0
    backoff_multiplier: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds cannot be negative.")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1.")


@dataclass(frozen=True, slots=True)
class PipelineStep:
    agent_name: str
    condition: Callable[[AgentContext], bool] | None = None
    retry_policy: RetryPolicy | None = None


@dataclass(frozen=True, slots=True)
class AgentPipeline:
    name: str
    steps: Sequence[PipelineStep]
    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL


class AgentPipelineEngine:
    """Dependency-aware orchestration with retries, caching, and events."""

    def __init__(
        self,
        registry: "AgentRegistry",
        *,
        cache: AgentResultCache | None = None,
        event_logger: AgentEventLogger | None = None,
        default_retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._registry = registry
        self._cache = cache
        self._event_logger = event_logger or NullAgentEventLogger()
        self._default_retry = default_retry_policy or RetryPolicy()

    def execute_agent(
        self,
        agent_name: str,
        context: AgentContext,
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> AgentResult:
        return self._execute_with_dependencies(
            agent_name,
            context,
            retry_policy=retry_policy,
            visiting=[],
        )

    def execute_pipeline(
        self,
        pipeline: AgentPipeline,
        context: AgentContext,
    ) -> PipelineResult:
        if pipeline.execution_mode is ExecutionMode.PARALLEL:
            raise NotImplementedError(
                "Parallel mode is reserved by the pipeline contract and will be "
                "implemented without changing agent APIs."
            )
        started = time.perf_counter()
        skipped: list[str] = []
        failures = 0
        for step in pipeline.steps:
            if step.condition is not None and not step.condition(context):
                skipped.append(step.agent_name)
                self._emit(
                    context,
                    AgentEvent(
                        event_type=AgentEventType.SKIPPED,
                        agent_name=step.agent_name,
                        message="Pipeline condition evaluated to false.",
                    ),
                )
                continue
            try:
                self.execute_agent(
                    step.agent_name,
                    context,
                    retry_policy=step.retry_policy,
                )
            except Exception:
                failures += 1
                raise
        duration = (time.perf_counter() - started) * 1000
        status = (
            PipelineStatus.PARTIAL
            if skipped or failures
            else PipelineStatus.COMPLETED
        )
        return PipelineResult(
            pipeline_name=pipeline.name,
            status=status,
            results=dict(context.results),
            skipped_agents=skipped,
            execution_time_ms=duration,
        )

    def dependency_order(self, agent_names: Sequence[str]) -> list[str]:
        order: list[str] = []
        visited: set[str] = set()
        visiting: list[str] = []

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                cycle = " -> ".join([*visiting, name])
                raise ValueError(f"Agent dependency cycle detected: {cycle}")
            visiting.append(name)
            agent = self._registry.get(name)
            for dependency in agent.dependencies():
                visit(dependency)
            visiting.pop()
            visited.add(name)
            order.append(name)

        for name in agent_names:
            visit(name)
        return order

    def _execute_with_dependencies(
        self,
        agent_name: str,
        context: AgentContext,
        *,
        retry_policy: RetryPolicy | None,
        visiting: list[str],
    ) -> AgentResult:
        if agent_name in context.results:
            return context.results[agent_name]
        if agent_name in visiting:
            cycle = " -> ".join([*visiting, agent_name])
            raise ValueError(f"Agent dependency cycle detected: {cycle}")

        agent = self._registry.get(agent_name)
        visiting.append(agent_name)
        for dependency in agent.dependencies():
            self._execute_with_dependencies(
                dependency,
                context,
                retry_policy=None,
                visiting=visiting,
            )
        visiting.pop()
        return self._run_agent(
            agent,
            context,
            retry_policy or self._default_retry,
        )

    def _run_agent(
        self,
        agent: BaseAgent,
        context: AgentContext,
        retry_policy: RetryPolicy,
    ) -> AgentResult:
        try:
            agent.validate(context)
        except Exception as error:
            self._emit(
                context,
                AgentEvent(
                    event_type=AgentEventType.FAILED,
                    agent_name=agent.name,
                    duration_ms=0.0,
                    message=str(error),
                    metadata={"phase": "validation"},
                ),
            )
            raise
        cache = context.cache or self._cache
        fingerprint = agent.cache_fingerprint(context)
        force_refresh = bool(context.configuration.get("force_refresh", False))
        if agent.cacheable and cache is not None and not force_refresh:
            cached = cache.get(
                agent_name=agent.name,
                agent_version=agent.version,
                dna_fingerprint=fingerprint,
            )
            if cached is not None:
                context.results[agent.name] = cached
                self._emit(
                    context,
                    AgentEvent(
                        event_type=AgentEventType.CACHE_HIT,
                        agent_name=agent.name,
                        message="Reused output for unchanged Specification DNA.",
                    ),
                )
                return cached

        self._emit(
            context,
            AgentEvent(
                event_type=AgentEventType.STARTED,
                agent_name=agent.name,
            ),
        )
        started = time.perf_counter()
        delay = retry_policy.initial_delay_seconds
        last_error: Exception | None = None
        for attempt in range(1, retry_policy.max_attempts + 1):
            try:
                result = agent.execute(context)
                if result.agent_name != agent.name:
                    raise ValueError(
                        f"Agent '{agent.name}' returned result for "
                        f"'{result.agent_name}'."
                    )
                duration = (time.perf_counter() - started) * 1000
                result = result.model_copy(
                    update={
                        "execution_time_ms": duration,
                        "attempts": attempt,
                        "cached": False,
                    }
                )
                context.results[agent.name] = result
                if agent.cacheable and cache is not None:
                    cache.set(
                        agent_name=agent.name,
                        agent_version=agent.version,
                        dna_fingerprint=fingerprint,
                        result=result,
                    )
                for warning in result.warnings:
                    self._emit(
                        context,
                        AgentEvent(
                            event_type=AgentEventType.WARNING,
                            agent_name=agent.name,
                            duration_ms=duration,
                            message=warning,
                        ),
                    )
                self._emit(
                    context,
                    AgentEvent(
                        event_type=AgentEventType.COMPLETED,
                        agent_name=agent.name,
                        duration_ms=duration,
                        metadata={"attempts": attempt},
                    ),
                )
                return result
            except Exception as error:
                last_error = error
                if attempt < retry_policy.max_attempts:
                    if delay:
                        time.sleep(delay)
                    delay *= retry_policy.backoff_multiplier

        duration = (time.perf_counter() - started) * 1000
        self._emit(
            context,
            AgentEvent(
                event_type=AgentEventType.FAILED,
                agent_name=agent.name,
                duration_ms=duration,
                message=str(last_error),
                metadata={"attempts": retry_policy.max_attempts},
            ),
        )
        assert last_error is not None
        raise last_error

    def _emit(self, context: AgentContext, event: AgentEvent) -> None:
        context.record(event)
        self._event_logger.log(event)
