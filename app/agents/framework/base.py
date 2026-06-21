from abc import ABC, abstractmethod

from app.agents.framework.models import AgentContext, AgentResult


class BaseAgent(ABC):
    """Minimal contract implemented by every independent AI capability."""

    version = "1"
    cacheable = True

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique registry name."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Short human-readable purpose."""

    @abstractmethod
    def execute(self, context: AgentContext) -> AgentResult:
        """Run the capability using only the supplied context."""

    @abstractmethod
    def validate(self, context: AgentContext) -> None:
        """Raise when required context is unavailable or invalid."""

    @abstractmethod
    def dependencies(self) -> tuple[str, ...]:
        """Return agent names that must complete first."""

    def cache_fingerprint(self, context: AgentContext) -> str:
        """Return the input fingerprint used for result caching."""
        return context.dna_fingerprint
