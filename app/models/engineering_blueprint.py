from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class EngineeringArtifactType(StrEnum):
    ENGINEERING_SUMMARY = "engineering_summary"
    USER_STORY = "user_story"
    ACCEPTANCE_CRITERION = "acceptance_criterion"
    BACKEND_TASK = "backend_task"
    REST_API = "rest_api"
    DATABASE_ENTITY = "database_entity"
    BUSINESS_RULE = "business_rule"
    EDGE_CASE = "edge_case"
    FAILURE_SCENARIO = "failure_scenario"
    INTEGRATION_TASK = "integration_task"
    SECURITY_CONSIDERATION = "security_consideration"
    PERFORMANCE_CONSIDERATION = "performance_consideration"
    TECHNICAL_RISK = "technical_risk"
    OPEN_QUESTION = "open_question"


class ArtifactProvenance(StrEnum):
    DOCUMENT_BACKED = "document_backed"
    AI_SUGGESTION = "ai_suggestion"
    AI_ASSUMPTION = "ai_assumption"
    NEEDS_CLARIFICATION = "needs_clarification"


class BlueprintHttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class EngineeringField(BaseModel):
    name: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    required: bool
    description: str = Field(min_length=1)


class EngineeringSummaryPayload(BaseModel):
    kind: Literal[EngineeringArtifactType.ENGINEERING_SUMMARY] = (
        EngineeringArtifactType.ENGINEERING_SUMMARY
    )
    summary: str = Field(min_length=1)


class UserStoryPayload(BaseModel):
    kind: Literal[EngineeringArtifactType.USER_STORY] = (
        EngineeringArtifactType.USER_STORY
    )
    actor: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    benefit: str = Field(min_length=1)
    story: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_story_format(self) -> "UserStoryPayload":
        normalized = " ".join(self.story.split()).casefold()
        if not (
            normalized.startswith("as a ")
            and " i want " in normalized
            and " so that " in normalized
        ):
            raise ValueError(
                "User stories must use 'As a ... I want ... So that ...' format."
            )
        return self


class AcceptanceCriterionPayload(BaseModel):
    kind: Literal[EngineeringArtifactType.ACCEPTANCE_CRITERION] = (
        EngineeringArtifactType.ACCEPTANCE_CRITERION
    )
    given: str = Field(min_length=1)
    when: str = Field(min_length=1)
    then: str = Field(min_length=1)
    measurable_outcome: str = Field(min_length=1)


class TaskPayload(BaseModel):
    kind: Literal[
        EngineeringArtifactType.BACKEND_TASK,
        EngineeringArtifactType.INTEGRATION_TASK,
    ]
    task: str = Field(min_length=1)
    deliverables: list[str] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)


class RestApiPayload(BaseModel):
    kind: Literal[EngineeringArtifactType.REST_API] = (
        EngineeringArtifactType.REST_API
    )
    endpoint: str = Field(min_length=1)
    method: BlueprintHttpMethod
    purpose: str = Field(min_length=1)
    request_fields: list[EngineeringField]
    response_fields: list[EngineeringField]
    status_codes: dict[str, str]
    authentication_needed: bool | None = None
    validation_rules: list[str]

    @field_validator("endpoint")
    @classmethod
    def endpoint_must_be_a_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("REST endpoints must begin with '/'.")
        return value


class DatabaseEntityPayload(BaseModel):
    kind: Literal[EngineeringArtifactType.DATABASE_ENTITY] = (
        EngineeringArtifactType.DATABASE_ENTITY
    )
    entity: str = Field(min_length=1)
    attributes: list[EngineeringField]
    relationships: list[str]
    primary_key: str | None = None
    foreign_keys: list[str]
    constraints: list[str]


class BusinessRulePayload(BaseModel):
    kind: Literal[EngineeringArtifactType.BUSINESS_RULE] = (
        EngineeringArtifactType.BUSINESS_RULE
    )
    rule: str = Field(min_length=1)
    engineering_interpretation: str = Field(min_length=1)


class ScenarioPayload(BaseModel):
    kind: Literal[
        EngineeringArtifactType.EDGE_CASE,
        EngineeringArtifactType.FAILURE_SCENARIO,
    ]
    scenario: str = Field(min_length=1)
    expected_behavior: str = Field(min_length=1)


class ConsiderationPayload(BaseModel):
    kind: Literal[
        EngineeringArtifactType.SECURITY_CONSIDERATION,
        EngineeringArtifactType.PERFORMANCE_CONSIDERATION,
    ]
    consideration: str = Field(min_length=1)
    engineering_action: str = Field(min_length=1)


class TechnicalRiskPayload(BaseModel):
    kind: Literal[EngineeringArtifactType.TECHNICAL_RISK] = (
        EngineeringArtifactType.TECHNICAL_RISK
    )
    risk: str = Field(min_length=1)
    impact: str = Field(min_length=1)
    mitigation_or_question: str = Field(min_length=1)


class OpenQuestionPayload(BaseModel):
    kind: Literal[EngineeringArtifactType.OPEN_QUESTION] = (
        EngineeringArtifactType.OPEN_QUESTION
    )
    missing_information: str = Field(min_length=1)
    question: str = Field(min_length=1)
    recommended_stakeholder: str = Field(min_length=1)

    @field_validator("question")
    @classmethod
    def question_must_end_correctly(cls, value: str) -> str:
        if not value.rstrip().endswith("?"):
            raise ValueError("Open questions must end with '?'.")
        return value


ArtifactPayload = Annotated[
    EngineeringSummaryPayload
    | UserStoryPayload
    | AcceptanceCriterionPayload
    | TaskPayload
    | RestApiPayload
    | DatabaseEntityPayload
    | BusinessRulePayload
    | ScenarioPayload
    | ConsiderationPayload
    | TechnicalRiskPayload
    | OpenQuestionPayload,
    Field(discriminator="kind"),
]


class BlueprintArtifact(BaseModel):
    artifact_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    artifact_type: EngineeringArtifactType
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    provenance: ArtifactProvenance
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_text: str | None = None
    suggestion_reason: str | None = None
    source_chunk_ids: list[str] = Field(min_length=1)
    source_sections: list[str] = Field(min_length=1)
    related_assumption_ids: list[str] = Field(default_factory=list)
    related_ambiguity_ids: list[str] = Field(default_factory=list)
    related_conflict_ids: list[str] = Field(default_factory=list)
    related_missing_requirement_ids: list[str] = Field(default_factory=list)
    traceability_score: float = Field(ge=0.0, le=1.0)
    payload: ArtifactPayload

    @field_validator(
        "source_chunk_ids",
        "source_sections",
        "related_assumption_ids",
        "related_ambiguity_ids",
        "related_conflict_ids",
        "related_missing_requirement_ids",
    )
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_provenance_and_payload(self) -> "BlueprintArtifact":
        if self.payload.kind is not self.artifact_type:
            raise ValueError("Artifact type must match its payload kind.")
        if self.provenance is ArtifactProvenance.DOCUMENT_BACKED:
            if not self.evidence_text:
                raise ValueError("Document-backed artifacts require evidence text.")
            if self.suggestion_reason or self.related_assumption_ids:
                raise ValueError(
                    "Document-backed artifacts cannot be labeled as suggestions "
                    "or assumptions."
                )
        elif self.provenance is ArtifactProvenance.AI_SUGGESTION:
            if not self.suggestion_reason:
                raise ValueError("AI suggestions require a suggestion reason.")
            if self.related_assumption_ids:
                raise ValueError(
                    "AI suggestions must not silently depend on assumptions."
                )
        elif self.provenance is ArtifactProvenance.AI_ASSUMPTION:
            if not self.suggestion_reason or not self.related_assumption_ids:
                raise ValueError(
                    "AI-assumption artifacts require a reason and assumption IDs."
                )
        elif self.provenance is ArtifactProvenance.NEEDS_CLARIFICATION:
            if "needs clarification" not in self.description.casefold():
                raise ValueError(
                    "Clarification artifacts must explicitly say "
                    "'Needs clarification'."
                )
            if self.artifact_type is not EngineeringArtifactType.OPEN_QUESTION:
                raise ValueError(
                    "Needs-clarification artifacts must be open questions."
                )
        return self


class RequirementEngineeringBlueprint(BaseModel):
    requirement_id: str = Field(min_length=1)
    requirement_title: str = Field(min_length=1)
    artifacts: list[BlueprintArtifact] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_requirement_and_minimum_coverage(
        self,
    ) -> "RequirementEngineeringBlueprint":
        if any(
            artifact.requirement_id != self.requirement_id
            for artifact in self.artifacts
        ):
            raise ValueError(
                "All blueprint artifacts must belong to the enclosing requirement."
            )
        kinds = {artifact.artifact_type for artifact in self.artifacts}
        if EngineeringArtifactType.ENGINEERING_SUMMARY not in kinds:
            raise ValueError("Every requirement requires an engineering summary.")
        if not (
            EngineeringArtifactType.USER_STORY in kinds
            or EngineeringArtifactType.OPEN_QUESTION in kinds
        ):
            raise ValueError(
                "Every requirement requires a user story or clarification question."
            )
        if not (
            EngineeringArtifactType.ACCEPTANCE_CRITERION in kinds
            or EngineeringArtifactType.OPEN_QUESTION in kinds
        ):
            raise ValueError(
                "Every requirement requires acceptance criteria or clarification."
            )
        return self


class BusinessToEngineeringOutput(BaseModel):
    requirement_blueprints: list[RequirementEngineeringBlueprint]


class EngineeringBlueprintResult(BaseModel):
    document_id: UUID
    requirement_blueprints: list[RequirementEngineeringBlueprint]
    total_requirements: int = Field(ge=0)
    total_artifacts: int = Field(ge=0)
    clarification_artifacts: int = Field(ge=0)
    cached: bool
    model: str
    agent_version: str
    source_fingerprint: str
    execution_time_ms: float = Field(ge=0.0)
    generated_at: datetime
    knowledge_graph_updated: bool
