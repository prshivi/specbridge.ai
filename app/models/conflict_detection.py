from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class DetectedConflictType(StrEnum):
    REQUIREMENT_VS_REQUIREMENT = "requirement_vs_requirement"
    BUSINESS_RULE_VS_BUSINESS_RULE = "business_rule_vs_business_rule"
    REQUIREMENT_VS_VALIDATION = "requirement_vs_validation"
    PERMISSION_ACCESS = "permission_access"
    WORKFLOW_SEQUENCE = "workflow_sequence"
    INTEGRATION_BEHAVIOR = "integration_behavior"
    DATA_RULE = "data_rule"
    NON_FUNCTIONAL = "non_functional"
    OVERLAP_DIFFERENT_MEANING = "overlap_different_meaning"
    ACCEPTANCE_CONDITION = "acceptance_condition"


class DetectedConflictSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecommendedStakeholder(StrEnum):
    BUSINESS = "business"
    PRODUCT = "product"
    ARCHITECT = "architect"
    BACKEND = "backend"
    FRONTEND = "frontend"
    SECURITY = "security"
    QA = "QA"
    DEVOPS = "DevOps"


class DetectedConflict(BaseModel):
    conflict_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    conflict_type: DetectedConflictType
    description: str = Field(min_length=1)
    severity: DetectedConflictSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    involved_requirement_ids: list[str] = Field(default_factory=list)
    involved_business_rule_ids: list[str] = Field(default_factory=list)
    evidence_texts: list[str] = Field(min_length=2)
    source_chunk_ids: list[str] = Field(min_length=1)
    source_sections: list[str] = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    recommended_resolution_question: str = Field(min_length=1)
    recommended_stakeholder: RecommendedStakeholder
    blocking_for_development: bool

    @field_validator(
        "involved_requirement_ids",
        "involved_business_rule_ids",
        "source_chunk_ids",
        "source_sections",
        "evidence_texts",
    )
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_participants_and_question(self) -> "DetectedConflict":
        involved = {
            *self.involved_requirement_ids,
            *self.involved_business_rule_ids,
        }
        if len(involved) < 2:
            raise ValueError("A conflict must involve at least two distinct items.")
        if not self.recommended_resolution_question.rstrip().endswith("?"):
            raise ValueError("The recommended resolution question must end with '?'.")
        return self


class ConflictDetectionOutput(BaseModel):
    conflicts: list[DetectedConflict]


class ConflictDetectionAgentResult(BaseModel):
    document_id: UUID
    conflicts: list[DetectedConflict]
    cached: bool
    model: str
    agent_version: str
    source_fingerprint: str
    execution_time_ms: float = Field(ge=0.0)
    analyzed_at: datetime
    knowledge_graph_updated: bool
