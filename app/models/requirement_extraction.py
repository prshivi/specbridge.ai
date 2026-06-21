from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class ExtractedRequirementCategory(StrEnum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    BUSINESS_RULE = "business_rule"
    VALIDATION_RULE = "validation_rule"
    PERMISSION_ACCESS = "permission_access"
    INTEGRATION = "integration"
    DATA = "data"
    REPORTING_ANALYTICS = "reporting_analytics"
    NOTIFICATION = "notification"
    COMPLIANCE_SECURITY = "compliance_security"


class ExtractedRequirementPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNSPECIFIED = "unspecified"


class EvidenceOrigin(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"


class ExtractedRequirement(BaseModel):
    requirement_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: ExtractedRequirementCategory
    priority: ExtractedRequirementPriority = ExtractedRequirementPriority.UNSPECIFIED
    confidence: float = Field(ge=0.0, le=1.0)
    source_chunk_ids: list[str] = Field(min_length=1)
    source_section: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    explicit_or_inferred: EvidenceOrigin
    ambiguity_flag: bool
    missing_info_flag: bool

    @field_validator("source_chunk_ids")
    @classmethod
    def unique_sources(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if not cleaned:
            raise ValueError("At least one source chunk is required.")
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def low_confidence_requires_ambiguity(self) -> "ExtractedRequirement":
        if self.confidence < 0.6 and not self.ambiguity_flag:
            raise ValueError(
                "Requirements with confidence below 0.6 must set ambiguity_flag=true."
            )
        return self


class RequirementExtraction(BaseModel):
    requirements: list[ExtractedRequirement]


class RequirementExtractionResult(BaseModel):
    document_id: UUID
    requirements: list[ExtractedRequirement]
    cached: bool
    model: str
    agent_version: str
    source_fingerprint: str
    execution_time_ms: float = Field(ge=0.0)
    extracted_at: datetime
    knowledge_graph_updated: bool
