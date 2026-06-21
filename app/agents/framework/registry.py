import importlib
import inspect
import pkgutil
from collections.abc import Iterable
from types import ModuleType

from app.agents.framework.base import BaseAgent
from app.agents.framework.models import AgentContext, AgentResult, PipelineResult
from app.agents.framework.pipeline import (
    AgentPipeline,
    AgentPipelineEngine,
    RetryPolicy,
)


class AgentRegistry:
    """Discover, register, and execute independent framework agents."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent | type[BaseAgent]) -> BaseAgent:
        instance = agent() if inspect.isclass(agent) else agent
        if not isinstance(instance, BaseAgent):
            raise TypeError("Only BaseAgent implementations can be registered.")
        if instance.name in self._agents:
            raise ValueError(f"Agent '{instance.name}' is already registered.")
        self._agents[instance.name] = instance
        return instance

    def register_many(
        self,
        agents: Iterable[BaseAgent | type[BaseAgent]],
    ) -> None:
        for agent in agents:
            self.register(agent)

    def discover(self, package_name: str = "app.agents") -> list[str]:
        package = importlib.import_module(package_name)
        modules = [package]
        if hasattr(package, "__path__"):
            modules.extend(
                importlib.import_module(module_info.name)
                for module_info in pkgutil.walk_packages(
                    package.__path__,
                    prefix=f"{package.__name__}.",
                )
                if ".framework" not in module_info.name
            )
        discovered: list[str] = []
        for module in modules:
            discovered.extend(self.discover_module(module))
        return discovered

    def discover_module(self, module: str | ModuleType) -> list[str]:
        loaded = importlib.import_module(module) if isinstance(module, str) else module
        discovered: list[str] = []
        for _, candidate in inspect.getmembers(loaded, inspect.isclass):
            if (
                candidate is BaseAgent
                or not issubclass(candidate, BaseAgent)
                or candidate.__module__ != loaded.__name__
                or inspect.isabstract(candidate)
            ):
                continue
            signature = inspect.signature(candidate)
            required = [
                parameter
                for parameter in signature.parameters.values()
                if parameter.default is inspect.Parameter.empty
                and parameter.kind
                in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                }
            ]
            if required:
                continue
            instance = self.register(candidate)
            discovered.append(instance.name)
        return discovered

    def get(self, name: str) -> BaseAgent:
        try:
            return self._agents[name]
        except KeyError as error:
            raise KeyError(f"Agent '{name}' is not registered.") from error

    def names(self) -> list[str]:
        return sorted(self._agents)

    def execute(
        self,
        name: str,
        context: AgentContext,
        *,
        engine: AgentPipelineEngine | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> AgentResult:
        executor = engine or AgentPipelineEngine(self)
        return executor.execute_agent(name, context, retry_policy=retry_policy)

    def execute_pipeline(
        self,
        pipeline: AgentPipeline,
        context: AgentContext,
        *,
        engine: AgentPipelineEngine | None = None,
    ) -> PipelineResult:
        executor = engine or AgentPipelineEngine(self)
        return executor.execute_pipeline(pipeline, context)
