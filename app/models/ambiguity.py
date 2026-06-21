from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class AmbiguityType(StrEnum):
    """Supported ambiguity and specification-gap categories."""

    VAGUE_LANGUAGE = "vague_language"
    MISSING_ACTOR = "missing_actor"
    MISSING_VALIDATION = "missing_validation"
    UNDEFINED_BUSINESS_RULE = "undefined_business_rule"
    MISSING_EDGE_CASE = "missing_edge_case"
    MISSING_ERROR_HANDLING = "missing_error_handling"
    UNDEFINED_INTEGRATION = "undefined_integration"


class IssueSeverity(StrEnum):
    """Potential delivery impact of an ambiguity."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AmbiguityIssue(BaseModel):
    """One grounded ambiguity or missing specification detail."""

    issue_id: str
    requirement_id: str
    source_chunk: str
    issue_type: AmbiguityType
    severity: IssueSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    clarification_question: str
    recommended_stakeholder: str


class RequirementAmbiguityAssessment(BaseModel):
    """Ambiguity assessment for exactly one requirement."""

    requirement_id: str
    source_chunk: str
    issues: list[AmbiguityIssue]


class AmbiguityAnalysis(BaseModel):
    """Complete ambiguity analysis covering every source requirement."""

    assessments: list[RequirementAmbiguityAssessment]


class AmbiguityDetectionResult(BaseModel):
    """Stored ambiguity analysis plus execution metadata."""

    document_id: UUID
    assessments: list[RequirementAmbiguityAssessment]
    total_requirements: int = Field(ge=0)
    total_issues: int = Field(ge=0)
    cached: bool
    model: str
    prompt_version: str
    analyzed_at: datetime
