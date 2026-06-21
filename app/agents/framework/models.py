import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentChunk, ParsedDocument
from app.models.knowledge import KnowledgeModel


@runtime_checkable
class LLMProvider(Protocol):
    """Provider-neutral interface available to framework agents."""

    def invoke(self, prompt: str, **kwargs: Any) -> Any:
        """Execute one model request."""


class AgentEventType(StrEnum):
    STARTED = "agent_started"
    COMPLETED = "agent_completed"
    FAILED = "agent_failed"
    WARNING = "agent_warning"
    CACHE_HIT = "agent_cache_hit"
    SKIPPED = "agent_skipped"


class AgentEvent(BaseModel):
    event_type: AgentEventType
    agent_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float | None = Field(default=None, ge=0.0)
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """Standard output envelope returned by every framework agent."""

    agent_name: str
    output: Any
    confidence: float = Field(ge=0.0, le=1.0)
    source_chunks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    execution_time_ms: float = Field(default=0.0, ge=0.0)
    cached: bool = False
    attempts: int = Field(default=1, ge=1)
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentContext(BaseModel):
    """Shared execution state passed through an agent pipeline."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    document: ParsedDocument | None = None
    knowledge_graph: KnowledgeModel | None = None
    specification_dna: Any = Field(default_factory=dict)
    chunks: list[DocumentChunk] = Field(default_factory=list)
    embeddings: dict[str, list[float]] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)
    llm_provider: LLMProvider | Any | None = Field(default=None, exclude=True)
    cache: Any | None = Field(default=None, exclude=True)
    execution_history: list[AgentEvent] = Field(default_factory=list)
    results: dict[str, AgentResult] = Field(default_factory=dict)

    @property
    def dna_fingerprint(self) -> str:
        """Return a stable cache key for the current Specification DNA."""
        dna = (
            self.specification_dna.model_dump(mode="json")
            if isinstance(self.specification_dna, BaseModel)
            else self.specification_dna
        )
        document_id = (
            self.document.id
            if self.document is not None
            else self.knowledge_graph.document_id
            if self.knowledge_graph is not None
            else self.chunks[0].document_id
            if self.chunks
            else None
        )
        payload = json.dumps(
            {"document_id": document_id, "specification_dna": dna},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def record(self, event: AgentEvent) -> None:
        self.execution_history.append(event)


class PipelineStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class PipelineResult(BaseModel):
    pipeline_name: str
    status: PipelineStatus
    results: dict[str, AgentResult]
    skipped_agents: list[str] = Field(default_factory=list)
    execution_time_ms: float = Field(ge=0.0)
