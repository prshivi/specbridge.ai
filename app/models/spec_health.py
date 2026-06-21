from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class HealthStatus(StrEnum):
    """Human-readable readiness band for a health score."""

    EXCELLENT = "excellent"
    GOOD = "good"
    CAUTION = "caution"
    CRITICAL = "critical"


class HealthMetric(BaseModel):
    """One explainable, normalized specification health metric."""

    key: str
    label: str
    score: float = Field(ge=0.0, le=100.0)
    status: HealthStatus
    summary: str


class HealthAction(BaseModel):
    """A prioritized action recommended before development starts."""

    priority: str
    action: str
    reason: str
    related_ids: list[str] = Field(default_factory=list)


class SpecHealthStatistics(BaseModel):
    """Evidence counts used to calculate the dashboard."""

    total_requirements: int = Field(ge=0)
    ambiguity_issues: int = Field(ge=0)
    conflicts: int = Field(ge=0)
    pending_assumptions: int = Field(ge=0)
    blocked_outputs: int = Field(ge=0)
    unresolved_architecture_decisions: int = Field(ge=0)
    requirements_needing_clarification: int = Field(ge=0)
    requirements_with_risks: int = Field(ge=0)


class SpecHealthDashboard(BaseModel):
    """Specification readiness dashboard derived from stored intelligence."""

    document_id: UUID
    analysis_mode: str = "ai"
    metrics: list[HealthMetric]
    overall_health: HealthMetric
    summary: str
    next_actions: list[HealthAction]
    statistics: SpecHealthStatistics
    scoring_note: str = (
        "All scores use a 0-100 scale where higher is better. "
        "Missing Information measures information coverage."
    )
