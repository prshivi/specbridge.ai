from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class ArchitectureStyle(StrEnum):
    """Supported high-level architecture styles."""

    MONOLITH = "monolith"
    MODULAR_MONOLITH = "modular_monolith"
    MICROSERVICES = "microservices"
    HYBRID = "hybrid"
    UNDETERMINED = "undetermined"


class ArchitectureRecommendation(BaseModel):
    """Shared recommendation rationale and provenance."""

    recommendation_id: str
    name: str
    recommendation: str
    why: str
    requirement_ids: list[str] = Field(min_length=1)
    source_chunks: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    inferred: bool
    inference_reason: str | None = None
    assumption_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_inference(self) -> "ArchitectureRecommendation":
        if self.inferred and (not self.inference_reason or not self.assumption_ids):
            raise ValueError(
                "Inferred architecture recommendations require a reason and assumption IDs."
            )
        if not self.inferred and (self.inference_reason or self.assumption_ids):
            raise ValueError(
                "Explicit architecture recommendations cannot cite inference metadata."
            )
        return self


class ArchitectureStyleRecommendation(ArchitectureRecommendation):
    """Recommended overall deployment and codebase style."""

    style: ArchitectureStyle
    rejected_styles: list[ArchitectureStyle]
    evolution_trigger: str | None = None


class ModuleRecommendation(ArchitectureRecommendation):
    """A logical application module and its responsibilities."""

    responsibilities: list[str]
    dependencies: list[str]


class ServiceRecommendation(ArchitectureRecommendation):
    """A deployable service candidate."""

    responsibilities: list[str]
    independently_deployable: bool
    extraction_trigger: str | None = None


class TechnologyRecommendation(ArchitectureRecommendation):
    """Recommendation for an infrastructure or platform concern."""

    option: str
    alternatives: list[str]
    operational_considerations: list[str]


class ExternalServiceRecommendation(ArchitectureRecommendation):
    """External managed service or provider recommendation."""

    purpose: str
    selection_criteria: list[str]


class MermaidDiagram(BaseModel):
    """A validated Mermaid diagram with rationale and traceability."""

    diagram_id: str
    title: str
    mermaid: str
    why: str
    requirement_ids: list[str] = Field(min_length=1)
    source_chunks: list[str] = Field(min_length=1)
    inferred: bool
    inference_reason: str | None = None
    assumption_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_inference(self) -> "MermaidDiagram":
        if self.inferred and (not self.inference_reason or not self.assumption_ids):
            raise ValueError("Inferred diagrams require a reason and assumption IDs.")
        if not self.inferred and (self.inference_reason or self.assumption_ids):
            raise ValueError("Explicit diagrams cannot cite inference metadata.")
        return self


class SequenceDiagram(MermaidDiagram):
    """A Mermaid interaction sequence."""

    @field_validator("mermaid")
    @classmethod
    def validate_sequence(cls, value: str) -> str:
        if not value.lstrip().startswith("sequenceDiagram"):
            raise ValueError("Sequence diagrams must start with sequenceDiagram.")
        return value


class ArchitectureFlowDiagram(MermaidDiagram):
    """A Mermaid architecture flowchart."""

    @field_validator("mermaid")
    @classmethod
    def validate_flowchart(cls, value: str) -> str:
        if not value.lstrip().startswith(("flowchart", "graph")):
            raise ValueError("Architecture diagrams must start with flowchart or graph.")
        return value


class ArchitectureDecisionGap(BaseModel):
    """Architecture choice blocked by missing requirements."""

    decision_id: str
    topic: str
    missing_information: str
    why_it_matters: str
    clarification_question: str
    requirement_ids: list[str] = Field(min_length=1)
    source_chunks: list[str] = Field(min_length=1)


class ArchitectureRecommendations(BaseModel):
    """Complete architecture recommendation package."""

    summary: str
    style: ArchitectureStyleRecommendation
    modules: list[ModuleRecommendation] = Field(min_length=1)
    services: list[ServiceRecommendation]
    database: TechnologyRecommendation
    caching: TechnologyRecommendation
    messaging: TechnologyRecommendation
    authentication: TechnologyRecommendation
    external_services: list[ExternalServiceRecommendation]
    deployment: TechnologyRecommendation
    architecture_diagram: ArchitectureFlowDiagram
    sequence_diagrams: list[SequenceDiagram] = Field(min_length=1)
    unresolved_decisions: list[ArchitectureDecisionGap]


class ArchitectureRecommendationResult(BaseModel):
    """Stored architecture recommendations plus execution metadata."""

    document_id: UUID
    architecture: ArchitectureRecommendations
    total_recommendations: int = Field(ge=0)
    inferred_recommendations: int = Field(ge=0)
    unresolved_decisions: int = Field(ge=0)
    cached: bool
    model: str
    prompt_version: str
    analyzed_at: datetime
