from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class ConflictSeverity(StrEnum):
    """Delivery impact of an unresolved contradiction."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConflictEvidence(BaseModel):
    """Requirement evidence participating in a contradiction."""

    requirement_id: str
    source_chunk: str
    statement: str


class RequirementConflict(BaseModel):
    """One grounded contradiction between requirements."""

    conflict_id: str
    conflict: str
    evidence: list[ConflictEvidence] = Field(min_length=2)
    severity: ConflictSeverity
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_chunks: list[str] = Field(min_length=2)


class ConflictAnalysis(BaseModel):
    """Complete cross-requirement conflict analysis."""

    conflicts: list[RequirementConflict]


class ConflictDetectionResult(BaseModel):
    """Stored conflict analysis plus execution metadata."""

    document_id: UUID
    conflicts: list[RequirementConflict]
    total_requirements: int = Field(ge=0)
    total_conflicts: int = Field(ge=0)
    cached: bool
    model: str
    prompt_version: str
    analyzed_at: datetime
