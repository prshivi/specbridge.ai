from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import EngineeringTranslationError
from app.models.ambiguity import AmbiguityDetectionResult
from app.models.assumptions import AssumptionLedgerResult
from app.models.conflicts import ConflictDetectionResult
from app.models.engineering import (
    AcceptanceCriterion,
    BlockedEngineeringOutput,
    DatabaseEntity,
    DatabaseField,
    EngineeringErrorCode,
    EngineeringPermission,
    EngineeringTask,
    EngineeringTranslation,
    EngineeringValidationRule,
    EventSuggestion,
    HttpMethod,
    OpenApiDraft,
    OpenApiOperation,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiSchema,
    OpenApiSchemaProperty,
    RestApiOperation,
    UserStory,
)
from app.models.requirements import RequirementIntelligenceResult
from app.models.understanding import SpecificationUnderstandingResult
from app.services.translation_store import EngineeringTranslationStore
from app.services.translator import BusinessToEngineeringTranslatorService
from app.tests.test_assumption_ledger import build_ledger
from app.tests.test_requirement_intelligence import (
    StubChunkService,
    build_chunks,
    build_requirement_result,
)
from app.tests.test_understanding_agent import build_understanding


class StubUnderstandingService:
    def understand(self, document_id: UUID) -> SpecificationUnderstandingResult:
        return SpecificationUnderstandingResult(
            document_id=document_id,
            understanding=build_understanding(),
            cached=True,
            model="understanding-model",
            prompt_version="specification-understanding-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubRequirementService:
    def get_requirements(self, document_id: UUID) -> RequirementIntelligenceResult:
        return RequirementIntelligenceResult(
            document_id=document_id,
            requirements=build_requirement_result(document_id).requirements,
            cached=True,
            model="requirements-model",
            prompt_version="requirement-intelligence-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubAmbiguityService:
    def detect(self, document_id: UUID) -> AmbiguityDetectionResult:
        return AmbiguityDetectionResult(
            document_id=document_id,
            assessments=[],
            total_requirements=0,
            total_issues=0,
            cached=True,
            model="ambiguity-model",
            prompt_version="ambiguity-detection-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubConflictService:
    def detect(self, document_id: UUID) -> ConflictDetectionResult:
        return ConflictDetectionResult(
            document_id=document_id,
            conflicts=[],
            total_requirements=2,
            total_conflicts=0,
            cached=True,
            model="conflict-model",
            prompt_version="conflict-detection-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubAssumptionService:
    def get_ledger(self, document_id: UUID) -> AssumptionLedgerResult:
        ledger = build_ledger(document_id)
        return AssumptionLedgerResult(
            document_id=document_id,
            facts=ledger.facts,
            assumptions=ledger.assumptions,
            total_facts=1,
            total_assumptions=1,
            pending_confirmation=1,
            cached=True,
            model="assumption-model",
            prompt_version="assumption-ledger-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubTranslatorProvider:
    def __init__(self, translation: EngineeringTranslation) -> None:
        self.translation = translation
        self.calls = 0
        self.context = ""

    def analyze(self, context: str) -> EngineeringTranslation:
        self.calls += 1
        self.context = context
        return self.translation


def explicit_metadata(document_id: UUID, artifact_id: str) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "requirement_ids": ["FR-001"],
        "source_chunks": [f"{document_id}:1"],
        "inferred": False,
    }


def inferred_metadata(document_id: UUID, artifact_id: str) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "requirement_ids": ["FR-001"],
        "source_chunks": [f"{document_id}:1"],
        "inferred": True,
        "inference_reason": "Uses the confirmed implementation assumption ASM-001.",
        "assumption_ids": ["ASM-001"],
    }


def build_translation(document_id: UUID) -> EngineeringTranslation:
    return EngineeringTranslation(
        user_stories=[
            UserStory(
                **explicit_metadata(document_id, "US-001"),
                actor="Customer",
                goal="submit an email address",
                benefit="the account can be validated",
                story=(
                    "As a customer, I want to submit an email address so that "
                    "the account can be validated."
                ),
            )
        ],
        acceptance_criteria=[
            AcceptanceCriterion(
                **explicit_metadata(document_id, "AC-001"),
                title="Validate customer email",
                given="A customer has entered an email address",
                when="The registration is submitted",
                then="The platform validates the email address",
            )
        ],
        rest_apis=[
            RestApiOperation(
                **inferred_metadata(document_id, "API-001"),
                method=HttpMethod.POST,
                path="/registrations",
                summary="Submit registration details",
                request_description=None,
                response_description="Registration validation outcome",
                permission=None,
            )
        ],
        openapi_draft=OpenApiDraft(
            **inferred_metadata(document_id, "OAS-001"),
            title="Registration API Draft",
            version="0.1.0",
            operations=[
                OpenApiOperation(
                    **inferred_metadata(document_id, "OAS-OP-001"),
                    method=HttpMethod.POST,
                    path="/registrations",
                    operation_id="submitRegistration",
                    summary="Submit a registration",
                    parameters=[
                        OpenApiParameter(
                            name="email",
                            location="body",
                            required=True,
                            schema_type="string",
                            description="Customer email supplied for validation",
                        )
                    ],
                    request_schema="RegistrationRequest",
                    responses=[
                        OpenApiResponse(
                            status_code="200",
                            description="Validation completed",
                        )
                    ],
                )
            ],
            schemas=[
                OpenApiSchema(
                    **inferred_metadata(document_id, "OAS-SCHEMA-001"),
                    name="RegistrationRequest",
                    description="Registration input supported by the requirement",
                    properties=[
                        OpenApiSchemaProperty(
                            name="email",
                            schema_type="string",
                            required=True,
                            description="Customer email address",
                        )
                    ],
                )
            ],
        ),
        database_entities=[
            DatabaseEntity(
                **inferred_metadata(document_id, "DB-001"),
                name="Registration",
                description="Stores registration validation state",
                fields=[
                    DatabaseField(
                        name="email",
                        data_type="string",
                        required=True,
                        description="Customer email address",
                    )
                ],
                relationships=[],
            )
        ],
        validation_rules=[
            EngineeringValidationRule(
                **explicit_metadata(document_id, "VAL-001"),
                field_or_object="email",
                rule="Validate the customer email address",
                failure_behavior=None,
            )
        ],
        backend_tasks=[
            EngineeringTask(
                **explicit_metadata(document_id, "TASK-BE-001"),
                title="Implement email validation",
                description="Implement the required customer email validation.",
                dependencies=[],
            )
        ],
        integration_tasks=[],
        permissions=[
            EngineeringPermission(
                artifact_id="PERM-ENG-001",
                requirement_ids=["PERM-001"],
                source_chunks=[f"{document_id}:2"],
                inferred=False,
                actor_or_role="Administrator",
                action="deactivate",
                resource="account",
                conditions=[],
            )
        ],
        error_codes=[
            EngineeringErrorCode(
                **inferred_metadata(document_id, "ERR-001"),
                code="EMAIL_VALIDATION_FAILED",
                message="Email validation failed",
                trigger="The required email validation does not pass",
                http_status=None,
            )
        ],
        event_suggestions=[
            EventSuggestion(
                **inferred_metadata(document_id, "EVT-001"),
                event_name="EmailValidated",
                trigger="Email validation completes",
                purpose="Allow downstream processing after validation",
                payload_fields=["email"],
            )
        ],
        blocked_outputs=[
            BlockedEngineeringOutput(
                **inferred_metadata(document_id, "BLOCK-001"),
                artifact_type="integration_task",
                missing_information="No external validation provider is specified.",
                clarification_question=(
                    "Should email validation use an external provider?"
                ),
            )
        ],
    )


def build_service(
    tmp_path: Path,
    document_id: UUID,
    translation: EngineeringTranslation,
) -> tuple[BusinessToEngineeringTranslatorService, StubTranslatorProvider]:
    settings = Settings(
        understanding_cache_db=tmp_path / "specbridge.db",
        openai_translator_model="test-translator-model",
    )
    provider = StubTranslatorProvider(translation)
    service = BusinessToEngineeringTranslatorService(
        settings,
        chunk_service=StubChunkService(build_chunks(document_id)),
        understanding_service=StubUnderstandingService(),
        requirement_service=StubRequirementService(),
        ambiguity_service=StubAmbiguityService(),
        conflict_service=StubConflictService(),
        assumption_service=StubAssumptionService(),
        store=EngineeringTranslationStore(settings.understanding_cache_db),
        provider=provider,
    )
    return service, provider


def test_translator_generates_all_artifact_groups_and_caches(tmp_path: Path) -> None:
    document_id = uuid4()
    service, provider = build_service(
        tmp_path,
        document_id,
        build_translation(document_id),
    )

    first = service.translate(document_id)
    second = service.translate(document_id)

    assert first.cached is False
    assert second.cached is True
    assert provider.calls == 1
    assert first.translation.user_stories
    assert first.translation.acceptance_criteria
    assert first.translation.rest_apis
    assert first.translation.openapi_draft.operations
    assert first.translation.openapi_draft.schemas
    assert first.translation.database_entities
    assert first.translation.validation_rules
    assert first.translation.backend_tasks
    assert first.translation.permissions
    assert first.translation.error_codes
    assert first.translation.event_suggestions
    assert first.translation.blocked_outputs
    assert first.inferred_artifacts > 0
    assert first.blocked_outputs == 1
    assert '"requirement_id": "FR-001"' in provider.context
    assert '"assumption_id": "ASM-001"' in provider.context


def test_translator_rejects_unknown_requirement(tmp_path: Path) -> None:
    document_id = uuid4()
    translation = build_translation(document_id)
    translation.user_stories[0].requirement_ids = ["FR-999"]
    service, _ = build_service(tmp_path, document_id, translation)

    with pytest.raises(EngineeringTranslationError, match="unknown requirements"):
        service.translate(document_id)


def test_translator_rejects_mismatched_source_chunks(tmp_path: Path) -> None:
    document_id = uuid4()
    translation = build_translation(document_id)
    translation.user_stories[0].source_chunks = [f"{document_id}:2"]
    service, _ = build_service(tmp_path, document_id, translation)

    with pytest.raises(EngineeringTranslationError, match="exactly match"):
        service.translate(document_id)


def test_translator_rejects_unknown_assumption(tmp_path: Path) -> None:
    document_id = uuid4()
    translation = build_translation(document_id)
    translation.event_suggestions[0].assumption_ids = ["ASM-999"]
    service, _ = build_service(tmp_path, document_id, translation)

    with pytest.raises(EngineeringTranslationError, match="unknown assumptions"):
        service.translate(document_id)


def test_inferred_artifact_requires_clear_marking(document_id: UUID = uuid4()) -> None:
    with pytest.raises(ValidationError, match="assumption ledger IDs"):
        EventSuggestion(
            artifact_id="EVT-001",
            requirement_ids=["FR-001"],
            source_chunks=[f"{document_id}:1"],
            inferred=True,
            inference_reason="This is inferred.",
            event_name="EmailValidated",
            trigger="Validation completes",
            purpose="Notify downstream consumers",
            payload_fields=[],
        )

