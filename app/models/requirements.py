from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class RequirementCategory(StrEnum):
    """Supported requirement intelligence categories."""

    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    BUSINESS_RULE = "business_rule"
    DEPENDENCY = "dependency"
    VALIDATION_RULE = "validation_rule"
    SECURITY = "security"
    PERMISSION = "permission"
    NOTIFICATION = "notification"
    AUDIT = "audit"


class RequirementPriority(StrEnum):
    """Normalized implementation priority."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Requirement(BaseModel):
    """One traceable requirement extracted from the specification."""

    requirement_id: str
    title: str
    description: str
    priority: RequirementPriority
    confidence: float = Field(ge=0.0, le=1.0)
    source_chunk: str
    category: RequirementCategory


class RequirementIntelligence(BaseModel):
    """All categorized requirements extracted from one specification."""

    requirements: list[Requirement]


class RequirementIntelligenceResult(BaseModel):
    """Stored requirement intelligence plus execution metadata."""

    document_id: UUID
    requirements: list[Requirement]
    cached: bool
    model: str
    prompt_version: str
    analyzed_at: datetime
