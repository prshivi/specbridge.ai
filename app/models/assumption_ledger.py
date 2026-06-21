from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class AssumptionType(StrEnum):
    MISSING_DETAIL = "missing_detail"
    INFERRED_GAP = "inferred_gap"
    TECHNICAL_TRANSLATION = "technical_translation"
    USER_ROLE = "user_role"
    VALIDATION = "validation"
    ERROR_HANDLING = "error_handling"
    INTEGRATION = "integration"
    DATA_FLOW = "data_flow"
    PERMISSION = "permission"
    NOTIFICATION = "notification"
    WORKFLOW = "workflow"
    OTHER = "other"


class AssumptionImpactArea(StrEnum):
    BUSINESS = "business"
    PRODUCT = "product"
    ARCHITECTURE = "architecture"
    BACKEND = "backend"
    FRONTEND = "frontend"
    SECURITY = "security"
    QA = "QA"
    DEVOPS = "DevOps"


class AssumptionRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AssumptionStatus(StrEnum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class LedgerFact(BaseModel):
    """A statement directly supported by specification evidence."""

    fact_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    source_chunk_ids: list[str] = Field(min_length=1)
    source_sections: list[str] = Field(min_length=1)
    related_requirement_ids: list[str] = Field(default_factory=list)

    @field_validator(
        "source_chunk_ids",
        "source_sections",
        "related_requirement_ids",
    )
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class LedgerAssumption(BaseModel):
    """An explicitly labeled inference that must never be presented as fact."""

    assumption_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    assumption_type: AssumptionType
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    source_chunk_ids: list[str] = Field(default_factory=list)
    source_sections: list[str] = Field(default_factory=list)
    related_requirement_ids: list[str] = Field(default_factory=list)
    related_ambiguity_ids: list[str] = Field(default_factory=list)
    related_conflict_ids: list[str] = Field(default_factory=list)
    related_missing_requirement_ids: list[str] = Field(default_factory=list)
    impact_area: AssumptionImpactArea
    risk_level: AssumptionRiskLevel
    needs_stakeholder_confirmation: bool
    confirmation_question: str = Field(min_length=1)
    status: AssumptionStatus = AssumptionStatus.OPEN

    @field_validator(
        "source_chunk_ids",
        "source_sections",
        "related_requirement_ids",
        "related_ambiguity_ids",
        "related_conflict_ids",
        "related_missing_requirement_ids",
    )
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_traceability(self) -> "LedgerAssumption":
        if not any(
            (
                self.source_chunk_ids,
                self.related_requirement_ids,
                self.related_ambiguity_ids,
                self.related_conflict_ids,
                self.related_missing_requirement_ids,
            )
        ):
            raise ValueError("An assumption must include contextual traceability.")
        if self.source_sections and not self.source_chunk_ids:
            raise ValueError("Source sections require source chunk IDs.")
        if not self.confirmation_question.rstrip().endswith("?"):
            raise ValueError("The confirmation question must end with '?'.")
        return self


class AssumptionLedgerOutput(BaseModel):
    facts: list[LedgerFact]
    assumptions: list[LedgerAssumption]


class FrameworkAssumptionLedgerResult(BaseModel):
    document_id: UUID
    facts: list[LedgerFact]
    assumptions: list[LedgerAssumption]
    cached: bool
    model: str
    agent_version: str
    source_fingerprint: str
    execution_time_ms: float = Field(ge=0.0)
    analyzed_at: datetime
    knowledge_graph_updated: bool


class AssumptionStatusUpdate(BaseModel):
    status: AssumptionStatus

    @field_validator("status")
    @classmethod
    def final_status_only(cls, value: AssumptionStatus) -> AssumptionStatus:
        if value is AssumptionStatus.OPEN:
            raise ValueError("PATCH status must be confirmed or rejected.")
        return value
