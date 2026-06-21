from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class HttpMethod(StrEnum):
    """Supported REST operation methods."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class EngineeringArtifact(BaseModel):
    """Shared traceability and inference metadata."""

    artifact_id: str
    requirement_ids: list[str] = Field(min_length=1)
    source_chunks: list[str] = Field(min_length=1)
    inferred: bool
    inference_reason: str | None = None
    assumption_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_inference_marker(self) -> "EngineeringArtifact":
        if self.inferred and not self.inference_reason:
            raise ValueError("Inferred artifacts require an inference reason.")
        if self.inferred and not self.assumption_ids:
            raise ValueError("Inferred artifacts require assumption ledger IDs.")
        if not self.inferred and self.inference_reason:
            raise ValueError("Explicit artifacts must not include an inference reason.")
        if not self.inferred and self.assumption_ids:
            raise ValueError("Explicit artifacts must not include assumption IDs.")
        return self


class UserStory(EngineeringArtifact):
    """Traceable user story."""

    actor: str
    goal: str
    benefit: str
    story: str


class AcceptanceCriterion(EngineeringArtifact):
    """Behavioral acceptance criterion."""

    title: str
    given: str
    when: str
    then: str


class RestApiOperation(EngineeringArtifact):
    """Proposed REST operation grounded in requirements."""

    method: HttpMethod
    path: str
    summary: str
    request_description: str | None = None
    response_description: str
    permission: str | None = None


class OpenApiParameter(BaseModel):
    """Draft OpenAPI operation parameter."""

    name: str
    location: str
    required: bool
    schema_type: str
    description: str


class OpenApiResponse(BaseModel):
    """Draft OpenAPI response."""

    status_code: str
    description: str


class OpenApiOperation(EngineeringArtifact):
    """An operation in the generated OpenAPI draft."""

    method: HttpMethod
    path: str
    operation_id: str
    summary: str
    parameters: list[OpenApiParameter]
    request_schema: str | None = None
    responses: list[OpenApiResponse]


class OpenApiSchemaProperty(BaseModel):
    """Property in a draft OpenAPI schema."""

    name: str
    schema_type: str
    required: bool
    description: str


class OpenApiSchema(EngineeringArtifact):
    """Schema component in the generated OpenAPI draft."""

    name: str
    description: str
    properties: list[OpenApiSchemaProperty]


class OpenApiDraft(EngineeringArtifact):
    """Structured OpenAPI 3.1 draft."""

    openapi: str = "3.1.0"
    title: str
    version: str
    operations: list[OpenApiOperation]
    schemas: list[OpenApiSchema]


class DatabaseField(BaseModel):
    """Field in a proposed database entity."""

    name: str
    data_type: str
    required: bool
    description: str


class DatabaseEntity(EngineeringArtifact):
    """Proposed persistent domain entity."""

    name: str
    description: str
    fields: list[DatabaseField]
    relationships: list[str]


class EngineeringValidationRule(EngineeringArtifact):
    """Implementation-facing validation rule."""

    field_or_object: str
    rule: str
    failure_behavior: str | None = None


class EngineeringTask(EngineeringArtifact):
    """Backend or integration implementation task."""

    title: str
    description: str
    dependencies: list[str]


class EngineeringPermission(EngineeringArtifact):
    """Role or actor permission."""

    actor_or_role: str
    action: str
    resource: str
    conditions: list[str]


class EngineeringErrorCode(EngineeringArtifact):
    """Proposed stable application error."""

    code: str
    message: str
    trigger: str
    http_status: int | None = Field(default=None, ge=100, le=599)


class EventSuggestion(EngineeringArtifact):
    """Suggested domain or integration event."""

    event_name: str
    trigger: str
    purpose: str
    payload_fields: list[str]


class BlockedEngineeringOutput(EngineeringArtifact):
    """Artifact that cannot be safely completed from available information."""

    artifact_type: str
    missing_information: str
    clarification_question: str


class EngineeringTranslation(BaseModel):
    """Complete business-to-engineering translation."""

    user_stories: list[UserStory]
    acceptance_criteria: list[AcceptanceCriterion]
    rest_apis: list[RestApiOperation]
    openapi_draft: OpenApiDraft
    database_entities: list[DatabaseEntity]
    validation_rules: list[EngineeringValidationRule]
    backend_tasks: list[EngineeringTask]
    integration_tasks: list[EngineeringTask]
    permissions: list[EngineeringPermission]
    error_codes: list[EngineeringErrorCode]
    event_suggestions: list[EventSuggestion]
    blocked_outputs: list[BlockedEngineeringOutput]


class EngineeringTranslationResult(BaseModel):
    """Stored engineering translation plus execution metadata."""

    document_id: UUID
    translation: EngineeringTranslation
    total_artifacts: int = Field(ge=0)
    inferred_artifacts: int = Field(ge=0)
    blocked_outputs: int = Field(ge=0)
    cached: bool
    model: str
    prompt_version: str
    analyzed_at: datetime
