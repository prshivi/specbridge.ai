from dataclasses import dataclass

from app.agents.framework import (
    AgentPipelineEngine,
    AgentRegistry,
    AgentResultCache,
    RetryPolicy,
    SQLiteAgentEventLogger,
)
from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class AgentRuntime:
    """Configured registry and execution engine for application composition."""

    registry: AgentRegistry
    engine: AgentPipelineEngine


def create_agent_runtime(
    settings: Settings,
    *,
    discovery_package: str = "app.agents",
) -> AgentRuntime:
    """Create the production framework runtime and auto-discover plug-in agents."""
    registry = AgentRegistry()
    registry.discover(discovery_package)
    engine = AgentPipelineEngine(
        registry,
        cache=AgentResultCache(settings.agent_framework_db),
        event_logger=SQLiteAgentEventLogger(settings.agent_framework_db),
        default_retry_policy=RetryPolicy(
            max_attempts=settings.agent_retry_attempts,
            initial_delay_seconds=settings.agent_retry_delay_seconds,
        ),
    )
    return AgentRuntime(registry=registry, engine=engine)
