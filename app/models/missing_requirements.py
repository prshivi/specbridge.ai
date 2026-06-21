from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.conflict_detection import RecommendedStakeholder


class MissingRequirementGapType(StrEnum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION_PERMISSIONS = "authorization_permissions"
    INPUT_VALIDATION = "input_validation"
    ERROR_HANDLING = "error_handling"
    EDGE_CASES = "edge_cases"
    AUDIT_LOGGING = "audit_logging"
    NOTIFICATIONS = "notifications"
    RETRY_BEHAVIOR = "retry_behavior"
    RATE_LIMITING = "rate_limiting"
    DATA_RETENTION = "data_retention"
    DATA_PRIVACY = "data_privacy"
    SECURITY_CONTROLS = "security_controls"
    MONITORING_OBSERVABILITY = "monitoring_observability"
    PERFORMANCE_EXPECTATIONS = "performance_expectations"
    SCALABILITY_EXPECTATIONS = "scalability_expectations"
    ACCESSIBILITY = "accessibility"
    INTERNATIONALIZATION_LOCALIZATION = "internationalization_localization"
    INTEGRATION_FAILURE_HANDLING = "integration_failure_handling"
    USER_ROLES = "user_roles"
    REPORTING_ANALYTICS = "reporting_analytics"
    BACKUP_RECOVERY = "backup_recovery"
    ADMIN_OPERATIONS = "admin_operations"
    CONFIGURATION_RULES = "configuration_rules"
    COMPLIANCE_REQUIREMENTS = "compliance_requirements"


class MissingRequirementSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GapEvidenceOrigin(StrEnum):
    EXPLICIT_GAP = "explicit_gap"
    INFERRED_GAP = "inferred_gap"


class MissingRequirementIssue(BaseModel):
    missing_requirement_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    gap_type: MissingRequirementGapType
    description: str = Field(min_length=1)
    severity: MissingRequirementSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    related_requirement_ids: list[str] = Field(default_factory=list)
    related_workflow_ids: list[str] = Field(default_factory=list)
    related_actor_ids: list[str] = Field(default_factory=list)
    source_chunk_ids: list[str] = Field(default_factory=list)
    source_sections: list[str] = Field(default_factory=list)
    why_it_matters: str = Field(min_length=1)
    suggested_requirement_text: str = Field(min_length=1)
    clarification_question: str = Field(min_length=1)
    recommended_stakeholder: RecommendedStakeholder
    blocking_for_development: bool
    explicit_gap_or_inferred_gap: GapEvidenceOrigin

    @field_validator(
        "related_requirement_ids",
        "related_workflow_ids",
        "related_actor_ids",
        "source_chunk_ids",
        "source_sections",
    )
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_traceability_and_question(self) -> "MissingRequirementIssue":
        has_anchor = any(
            (
                self.related_requirement_ids,
                self.related_workflow_ids,
                self.related_actor_ids,
                self.source_chunk_ids,
            )
        )
        if not has_anchor:
            raise ValueError(
                "A missing requirement issue must include contextual traceability."
            )
        if self.source_sections and not self.source_chunk_ids:
            raise ValueError("Source sections require source chunk IDs.")
        if not self.clarification_question.rstrip().endswith("?"):
            raise ValueError("The clarification question must end with '?'.")
        return self


class MissingRequirementDetectionOutput(BaseModel):
    missing_requirements: list[MissingRequirementIssue]


class MissingRequirementDetectionResult(BaseModel):
    document_id: UUID
    missing_requirements: list[MissingRequirementIssue]
    cached: bool
    model: str
    agent_version: str
    source_fingerprint: str
    execution_time_ms: float = Field(ge=0.0)
    analyzed_at: datetime
    knowledge_graph_updated: bool
