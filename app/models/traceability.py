from uuid import UUID

from pydantic import BaseModel, Field


class TraceabilityArtifact(BaseModel):
    """A compact downstream artifact reference."""

    artifact_id: str
    summary: str
    inferred: bool


class TraceabilityAssumption(BaseModel):
    """An assumption affecting the traced requirement or output."""

    assumption_id: str
    assumption: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_confirmation: bool


class TraceabilityClarification(BaseModel):
    """A clarification needed for an ambiguity or blocked output."""

    clarification_id: str
    question: str
    recommended_stakeholder: str | None = None


class TraceabilityRisk(BaseModel):
    """An ambiguity or conflict risk affecting a requirement."""

    risk_id: str
    risk_type: str
    severity: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)


class SourceSection(BaseModel):
    """Original source location for a requirement."""

    source_chunk: str
    page: int | None = Field(default=None, ge=1)
    heading: str | None = None
    section: str | None = None


class TraceabilityRow(BaseModel):
    """Complete requirement-to-delivery traceability chain."""

    requirement_id: str
    business_requirement: str
    category: str
    priority: str
    user_stories: list[TraceabilityArtifact]
    apis: list[TraceabilityArtifact]
    database_entities: list[TraceabilityArtifact]
    backend_tasks: list[TraceabilityArtifact]
    acceptance_criteria: list[TraceabilityArtifact]
    assumptions: list[TraceabilityAssumption]
    clarifications: list[TraceabilityClarification]
    risks: list[TraceabilityRisk]
    source_section: SourceSection


class TraceabilityMatrix(BaseModel):
    """Complete traceability matrix for one specification."""

    document_id: UUID
    rows: list[TraceabilityRow]
    total_requirements: int = Field(ge=0)
    requirements_with_risks: int = Field(ge=0)
    requirements_needing_clarification: int = Field(ge=0)

