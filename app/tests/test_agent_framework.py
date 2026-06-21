import sqlite3
from pathlib import Path

import pytest

from app.agents.framework import (
    AgentContext,
    AgentEventType,
    AgentPipeline,
    AgentPipelineEngine,
    AgentRegistry,
    AgentResult,
    AgentResultCache,
    BaseAgent,
    ExecutionMode,
    InMemoryAgentEventLogger,
    PipelineStatus,
    PipelineStep,
    RetryPolicy,
    SQLiteAgentEventLogger,
)
from app.core.config import Settings
from app.services.agent_framework import create_agent_runtime


class SourceAgent(BaseAgent):
    calls = 0

    @property
    def name(self) -> str:
        return "source"

    @property
    def description(self) -> str:
        return "Produces a source value."

    def execute(self, context: AgentContext) -> AgentResult:
        type(self).calls += 1
        return AgentResult(
            agent_name=self.name,
            output={"value": context.specification_dna["value"]},
            confidence=0.95,
            source_chunks=["chunk-1"],
        )

    def validate(self, context: AgentContext) -> None:
        if "value" not in context.specification_dna:
            raise ValueError("Specification DNA value is required.")

    def dependencies(self) -> tuple[str, ...]:
        return ()


class DependentAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "dependent"

    @property
    def description(self) -> str:
        return "Consumes the source agent."

    def execute(self, context: AgentContext) -> AgentResult:
        source = context.results["source"].output["value"]
        return AgentResult(
            agent_name=self.name,
            output={"doubled": source * 2},
            confidence=0.9,
            warnings=["Fixture warning."],
        )

    def validate(self, context: AgentContext) -> None:
        del context

    def dependencies(self) -> tuple[str, ...]:
        return ("source",)


class RetryingAgent(BaseAgent):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "retrying"

    @property
    def description(self) -> str:
        return "Fails once before succeeding."

    def execute(self, context: AgentContext) -> AgentResult:
        del context
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("Transient failure.")
        return AgentResult(
            agent_name=self.name,
            output={"ok": True},
            confidence=1.0,
        )

    def validate(self, context: AgentContext) -> None:
        del context

    def dependencies(self) -> tuple[str, ...]:
        return ()


class CycleAgentA(SourceAgent):
    @property
    def name(self) -> str:
        return "cycle_a"

    def dependencies(self) -> tuple[str, ...]:
        return ("cycle_b",)


class CycleAgentB(SourceAgent):
    @property
    def name(self) -> str:
        return "cycle_b"

    def dependencies(self) -> tuple[str, ...]:
        return ("cycle_a",)


def build_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register_many([SourceAgent(), DependentAgent()])
    return registry


def test_registry_auto_discovers_zero_configuration_agents() -> None:
    registry = AgentRegistry()

    discovered = registry.discover("app.tests.fixture_agents")

    assert discovered == ["discovered_fixture"]
    assert registry.names() == ["discovered_fixture"]


def test_dependency_resolution_executes_prerequisites_and_logs_events() -> None:
    SourceAgent.calls = 0
    registry = build_registry()
    logger = InMemoryAgentEventLogger()
    engine = AgentPipelineEngine(registry, event_logger=logger)
    context = AgentContext(specification_dna={"value": 4})

    result = engine.execute_agent("dependent", context)

    assert result.output == {"doubled": 8}
    assert list(context.results) == ["source", "dependent"]
    assert SourceAgent.calls == 1
    event_types = [event.event_type for event in logger.events]
    assert event_types.count(AgentEventType.STARTED) == 2
    assert event_types.count(AgentEventType.COMPLETED) == 2
    assert AgentEventType.WARNING in event_types


def test_pipeline_supports_conditions_and_reports_partial_status() -> None:
    registry = build_registry()
    context = AgentContext(specification_dna={"value": 3})
    pipeline = AgentPipeline(
        name="conditional",
        steps=[
            PipelineStep("source"),
            PipelineStep("dependent", condition=lambda _: False),
        ],
    )

    result = registry.execute_pipeline(pipeline, context)

    assert result.status is PipelineStatus.PARTIAL
    assert result.skipped_agents == ["dependent"]
    assert "source" in result.results
    assert "dependent" not in result.results


def test_retry_policy_retries_transient_failures() -> None:
    agent = RetryingAgent()
    registry = AgentRegistry()
    registry.register(agent)

    result = registry.execute(
        "retrying",
        AgentContext(),
        retry_policy=RetryPolicy(max_attempts=2),
    )

    assert result.attempts == 2
    assert agent.calls == 2


def test_cache_reuses_results_only_when_dna_is_unchanged(tmp_path: Path) -> None:
    SourceAgent.calls = 0
    registry = AgentRegistry()
    registry.register(SourceAgent())
    engine = AgentPipelineEngine(
        registry,
        cache=AgentResultCache(tmp_path / "agents.db"),
    )

    first = engine.execute_agent(
        "source",
        AgentContext(specification_dna={"value": 5}),
    )
    second = engine.execute_agent(
        "source",
        AgentContext(specification_dna={"value": 5}),
    )
    third = engine.execute_agent(
        "source",
        AgentContext(specification_dna={"value": 6}),
    )

    assert first.cached is False
    assert second.cached is True
    assert third.cached is False
    assert SourceAgent.calls == 2


def test_dependency_cycle_is_rejected() -> None:
    registry = AgentRegistry()
    registry.register_many([CycleAgentA(), CycleAgentB()])
    engine = AgentPipelineEngine(registry)

    with pytest.raises(ValueError, match="cycle_a -> cycle_b -> cycle_a"):
        engine.execute_agent(
            "cycle_a",
            AgentContext(specification_dna={"value": 1}),
        )


def test_parallel_mode_is_reserved_without_changing_pipeline_contract() -> None:
    registry = build_registry()
    pipeline = AgentPipeline(
        name="future-parallel",
        steps=[PipelineStep("source")],
        execution_mode=ExecutionMode.PARALLEL,
    )

    with pytest.raises(NotImplementedError, match="Parallel mode is reserved"):
        registry.execute_pipeline(
            pipeline,
            AgentContext(specification_dna={"value": 1}),
        )


def test_validation_failures_are_recorded() -> None:
    registry = AgentRegistry()
    registry.register(SourceAgent())
    logger = InMemoryAgentEventLogger()
    engine = AgentPipelineEngine(registry, event_logger=logger)

    with pytest.raises(ValueError, match="DNA value"):
        engine.execute_agent("source", AgentContext())

    assert logger.events[-1].event_type is AgentEventType.FAILED
    assert logger.events[-1].metadata["phase"] == "validation"


def test_sqlite_event_logger_and_runtime_configuration(tmp_path: Path) -> None:
    database = tmp_path / "framework.db"
    event_logger = SQLiteAgentEventLogger(database)
    registry = AgentRegistry()
    registry.register(SourceAgent())
    engine = AgentPipelineEngine(registry, event_logger=event_logger)
    engine.execute_agent(
        "source",
        AgentContext(specification_dna={"value": 2}),
    )

    with sqlite3.connect(database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM agent_events").fetchone()[0]
    assert count == 2

    runtime = create_agent_runtime(
        Settings(
            agent_framework_db=tmp_path / "runtime.db",
            agent_retry_attempts=3,
            agent_retry_delay_seconds=0,
            _env_file=None,
        ),
        discovery_package="app.tests.fixture_agents",
    )
    assert runtime.registry.names() == ["discovered_fixture"]
