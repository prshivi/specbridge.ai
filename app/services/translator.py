import hashlib
import json
from datetime import UTC, datetime
from itertools import chain
from uuid import UUID

from app.agents.translator import OpenAITranslatorProvider, TranslatorModelProvider
from app.core.config import Settings
from app.core.exceptions import (
    EngineeringTranslationError,
    EngineeringTranslationNotConfiguredError,
)
from app.models.ambiguity import AmbiguityDetectionResult
from app.models.assumptions import AssumptionLedgerResult
from app.models.conflicts import ConflictDetectionResult
from app.models.document import DocumentChunk
from app.models.engineering import EngineeringArtifact, EngineeringTranslation
from app.models.engineering import EngineeringTranslationResult
from app.models.requirements import Requirement, RequirementIntelligenceResult
from app.models.understanding import SpecificationUnderstandingResult
from app.services.ambiguity import AmbiguityDetectionService
from app.services.assumptions import AssumptionLedgerService
from app.services.chunks import ChunkService
from app.services.conflicts import ConflictDetectionService
from app.services.requirements import RequirementIntelligenceService
from app.services.translation_store import EngineeringTranslationStore
from app.services.understanding import SpecificationUnderstandingService

PROMPT_VERSION = "business-to-engineering-v1"


class BusinessToEngineeringTranslatorService:
    """Generate and persist traceable engineering artifacts."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        understanding_service: SpecificationUnderstandingService | None = None,
        requirement_service: RequirementIntelligenceService | None = None,
        ambiguity_service: AmbiguityDetectionService | None = None,
        conflict_service: ConflictDetectionService | None = None,
        assumption_service: AssumptionLedgerService | None = None,
        store: EngineeringTranslationStore | None = None,
        provider: TranslatorModelProvider | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_translator_model
        self._chunk_service = chunk_service or ChunkService(settings)
        self._understanding_service = understanding_service or (
            SpecificationUnderstandingService(settings)
        )
        self._requirement_service = requirement_service or (
            RequirementIntelligenceService(settings)
        )
        self._ambiguity_service = ambiguity_service or AmbiguityDetectionService(
            settings
        )
        self._conflict_service = conflict_service or ConflictDetectionService(settings)
        self._assumption_service = assumption_service or AssumptionLedgerService(
            settings
        )
        self._store = store or EngineeringTranslationStore(
            settings.understanding_cache_db
        )
        self._provider = provider

    def translate(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> EngineeringTranslationResult:
        chunks = self._chunk_service.get_chunks(document_id)
        understanding = self._understanding_service.understand(document_id)
        requirements = self._requirement_service.get_requirements(document_id)
        ambiguities = self._ambiguity_service.detect(document_id)
        conflicts = self._conflict_service.detect(document_id)
        assumptions = self._assumption_service.get_ledger(document_id)
        context = self._assemble_context(
            document_id=document_id,
            chunks=chunks,
            understanding=understanding,
            requirements=requirements,
            ambiguities=ambiguities,
            conflicts=conflicts,
            assumptions=assumptions,
        )
        fingerprint = hashlib.sha256(context.encode("utf-8")).hexdigest()

        if not force_refresh:
            cached = self._store.get(
                document_id=document_id,
                fingerprint=fingerprint,
                model=self._model,
                prompt_version=PROMPT_VERSION,
            )
            if cached:
                translation, analyzed_at = cached
                return self._response(
                    document_id=document_id,
                    translation=translation,
                    cached=True,
                    analyzed_at=analyzed_at,
                )

        try:
            provider = self._provider or self._create_provider(self._settings)
            translation = provider.analyze(context)
            self._validate_translation(
                translation=translation,
                requirements=requirements.requirements,
                chunks=chunks,
                assumptions=assumptions,
            )
        except EngineeringTranslationError:
            raise
        except Exception as error:
            raise EngineeringTranslationError(
                "The business-to-engineering translation model call failed."
            ) from error

        analyzed_at = datetime.now(UTC)
        self._store.set(
            document_id=document_id,
            fingerprint=fingerprint,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            result=translation,
            analyzed_at=analyzed_at,
        )
        return self._response(
            document_id=document_id,
            translation=translation,
            cached=False,
            analyzed_at=analyzed_at,
        )

    def _response(
        self,
        *,
        document_id: UUID,
        translation: EngineeringTranslation,
        cached: bool,
        analyzed_at: datetime,
    ) -> EngineeringTranslationResult:
        artifacts = list(self._iter_artifacts(translation))
        return EngineeringTranslationResult(
            document_id=document_id,
            translation=translation,
            total_artifacts=len(artifacts),
            inferred_artifacts=sum(artifact.inferred for artifact in artifacts),
            blocked_outputs=len(translation.blocked_outputs),
            cached=cached,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            analyzed_at=analyzed_at,
        )

    @staticmethod
    def _assemble_context(
        *,
        document_id: UUID,
        chunks: list[DocumentChunk],
        understanding: SpecificationUnderstandingResult,
        requirements: RequirementIntelligenceResult,
        ambiguities: AmbiguityDetectionResult,
        conflicts: ConflictDetectionResult,
        assumptions: AssumptionLedgerResult,
    ) -> str:
        payload = {
            "document_id": str(document_id),
            "source_chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            "specification_understanding": understanding.understanding.model_dump(
                mode="json"
            ),
            "requirements": [
                requirement.model_dump(mode="json")
                for requirement in requirements.requirements
            ],
            "ambiguities": [
                assessment.model_dump(mode="json")
                for assessment in ambiguities.assessments
            ],
            "conflicts": [
                conflict.model_dump(mode="json") for conflict in conflicts.conflicts
            ],
            "assumption_ledger": {
                "facts": [fact.model_dump(mode="json") for fact in assumptions.facts],
                "assumptions": [
                    assumption.model_dump(mode="json")
                    for assumption in assumptions.assumptions
                ],
            },
        }
        return json.dumps(payload, indent=2)

    @classmethod
    def _validate_translation(
        cls,
        *,
        translation: EngineeringTranslation,
        requirements: list[Requirement],
        chunks: list[DocumentChunk],
        assumptions: AssumptionLedgerResult,
    ) -> None:
        requirement_map = {
            requirement.requirement_id: requirement for requirement in requirements
        }
        valid_chunks = {chunk.id for chunk in chunks}
        valid_assumptions = {
            assumption.assumption_id for assumption in assumptions.assumptions
        }
        blocked_artifact_ids = {
            artifact.artifact_id for artifact in translation.blocked_outputs
        }
        artifacts = list(cls._iter_artifacts(translation))
        artifact_ids = [artifact.artifact_id for artifact in artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise EngineeringTranslationError(
                "Engineering artifact IDs must be unique within a document."
            )

        for artifact in artifacts:
            unknown_requirements = set(artifact.requirement_ids) - set(requirement_map)
            if unknown_requirements:
                raise EngineeringTranslationError(
                    "Engineering artifacts referenced unknown requirements: "
                    + ", ".join(sorted(unknown_requirements))
                )
            expected_chunks = {
                requirement_map[requirement_id].source_chunk
                for requirement_id in artifact.requirement_ids
            }
            if (
                set(artifact.source_chunks) != expected_chunks
                or not expected_chunks.issubset(valid_chunks)
            ):
                raise EngineeringTranslationError(
                    "Engineering artifact source chunks must exactly match requirements."
                )
            if set(artifact.assumption_ids) - valid_assumptions:
                raise EngineeringTranslationError(
                    "Inferred artifacts referenced unknown assumptions."
                )
            if artifact.artifact_id in blocked_artifact_ids and not artifact.inferred:
                raise EngineeringTranslationError(
                    "Blocked outputs must be marked as inferred."
                )

    @staticmethod
    def _iter_artifacts(
        translation: EngineeringTranslation,
    ) -> chain[EngineeringArtifact]:
        groups = [
            translation.user_stories,
            translation.acceptance_criteria,
            translation.rest_apis,
            [translation.openapi_draft],
            translation.openapi_draft.operations,
            translation.openapi_draft.schemas,
            translation.database_entities,
            translation.validation_rules,
            translation.backend_tasks,
            translation.integration_tasks,
            translation.permissions,
            translation.error_codes,
            translation.event_suggestions,
            translation.blocked_outputs,
        ]
        return chain.from_iterable(groups)

    @staticmethod
    def _create_provider(settings: Settings) -> TranslatorModelProvider:
        api_key = (
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise EngineeringTranslationNotConfiguredError(
                "OPENAI_API_KEY is required to run engineering translation."
            )
        return OpenAITranslatorProvider(
            api_key=api_key,
            model=settings.openai_translator_model,
        )
