import hashlib
import json
from datetime import UTC, datetime
from itertools import chain
from uuid import UUID

from app.agents.architecture import (
    ArchitectureModelProvider,
    OpenAIArchitectureProvider,
)
from app.core.config import Settings
from app.core.exceptions import (
    ArchitectureRecommendationError,
    ArchitectureRecommendationNotConfiguredError,
)
from app.models.ambiguity import AmbiguityDetectionResult
from app.models.architecture import (
    ArchitectureRecommendation,
    ArchitectureRecommendationResult,
    ArchitectureRecommendations,
    MermaidDiagram,
)
from app.models.assumptions import AssumptionLedgerResult
from app.models.conflicts import ConflictDetectionResult
from app.models.document import DocumentChunk
from app.models.engineering import EngineeringTranslationResult
from app.models.requirements import Requirement, RequirementIntelligenceResult
from app.models.understanding import SpecificationUnderstandingResult
from app.services.ambiguity import AmbiguityDetectionService
from app.services.architecture_store import ArchitectureRecommendationStore
from app.services.assumptions import AssumptionLedgerService
from app.services.chunks import ChunkService
from app.services.conflicts import ConflictDetectionService
from app.services.requirements import RequirementIntelligenceService
from app.services.translator import BusinessToEngineeringTranslatorService
from app.services.understanding import SpecificationUnderstandingService

PROMPT_VERSION = "architecture-recommendations-v1"


class ArchitectureRecommendationService:
    """Generate and persist traceable architecture recommendations."""

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
        translator_service: BusinessToEngineeringTranslatorService | None = None,
        store: ArchitectureRecommendationStore | None = None,
        provider: ArchitectureModelProvider | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_architecture_model
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
        self._translator_service = translator_service or (
            BusinessToEngineeringTranslatorService(settings)
        )
        self._store = store or ArchitectureRecommendationStore(
            settings.understanding_cache_db
        )
        self._provider = provider

    def recommend(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> ArchitectureRecommendationResult:
        chunks = self._chunk_service.get_chunks(document_id)
        understanding = self._understanding_service.understand(document_id)
        requirements = self._requirement_service.get_requirements(document_id)
        ambiguities = self._ambiguity_service.detect(document_id)
        conflicts = self._conflict_service.detect(document_id)
        assumptions = self._assumption_service.get_ledger(document_id)
        engineering = self._translator_service.translate(document_id)
        context = self._assemble_context(
            document_id=document_id,
            chunks=chunks,
            understanding=understanding,
            requirements=requirements,
            ambiguities=ambiguities,
            conflicts=conflicts,
            assumptions=assumptions,
            engineering=engineering,
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
                architecture, analyzed_at = cached
                return self._response(
                    document_id=document_id,
                    architecture=architecture,
                    cached=True,
                    analyzed_at=analyzed_at,
                )

        try:
            provider = self._provider or self._create_provider(self._settings)
            architecture = provider.analyze(context)
            self._validate_recommendations(
                architecture=architecture,
                requirements=requirements.requirements,
                chunks=chunks,
                assumptions=assumptions,
            )
        except ArchitectureRecommendationError:
            raise
        except Exception as error:
            raise ArchitectureRecommendationError(
                "The architecture recommendation model call failed."
            ) from error

        analyzed_at = datetime.now(UTC)
        self._store.set(
            document_id=document_id,
            fingerprint=fingerprint,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            result=architecture,
            analyzed_at=analyzed_at,
        )
        return self._response(
            document_id=document_id,
            architecture=architecture,
            cached=False,
            analyzed_at=analyzed_at,
        )

    def _response(
        self,
        *,
        document_id: UUID,
        architecture: ArchitectureRecommendations,
        cached: bool,
        analyzed_at: datetime,
    ) -> ArchitectureRecommendationResult:
        recommendations = list(self._iter_recommendations(architecture))
        return ArchitectureRecommendationResult(
            document_id=document_id,
            architecture=architecture,
            total_recommendations=len(recommendations),
            inferred_recommendations=sum(item.inferred for item in recommendations),
            unresolved_decisions=len(architecture.unresolved_decisions),
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
        engineering: EngineeringTranslationResult,
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
            "engineering_translation": engineering.translation.model_dump(mode="json"),
        }
        return json.dumps(payload, indent=2)

    @classmethod
    def _validate_recommendations(
        cls,
        *,
        architecture: ArchitectureRecommendations,
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
        recommendations = list(cls._iter_recommendations(architecture))
        recommendation_ids = [
            item.recommendation_id
            if isinstance(item, ArchitectureRecommendation)
            else item.diagram_id
            for item in recommendations
        ]
        if len(recommendation_ids) != len(set(recommendation_ids)):
            raise ArchitectureRecommendationError(
                "Architecture recommendation IDs must be unique."
            )

        for item in recommendations:
            requirement_ids = item.requirement_ids
            unknown_requirements = set(requirement_ids) - set(requirement_map)
            if unknown_requirements:
                raise ArchitectureRecommendationError(
                    "Architecture recommendations referenced unknown requirements: "
                    + ", ".join(sorted(unknown_requirements))
                )
            expected_chunks = {
                requirement_map[requirement_id].source_chunk
                for requirement_id in requirement_ids
            }
            if (
                set(item.source_chunks) != expected_chunks
                or not expected_chunks.issubset(valid_chunks)
            ):
                raise ArchitectureRecommendationError(
                    "Architecture source chunks must exactly match requirements."
                )
            if set(item.assumption_ids) - valid_assumptions:
                raise ArchitectureRecommendationError(
                    "Architecture recommendations referenced unknown assumptions."
                )

        for decision in architecture.unresolved_decisions:
            unknown_requirements = set(decision.requirement_ids) - set(requirement_map)
            expected_chunks = {
                requirement_map[requirement_id].source_chunk
                for requirement_id in decision.requirement_ids
                if requirement_id in requirement_map
            }
            if unknown_requirements or set(decision.source_chunks) != expected_chunks:
                raise ArchitectureRecommendationError(
                    "Unresolved architecture decisions must be requirement-traceable."
                )

    @staticmethod
    def _iter_recommendations(
        architecture: ArchitectureRecommendations,
    ) -> chain[ArchitectureRecommendation | MermaidDiagram]:
        groups = [
            [architecture.style],
            architecture.modules,
            architecture.services,
            [architecture.database],
            [architecture.caching],
            [architecture.messaging],
            [architecture.authentication],
            architecture.external_services,
            [architecture.deployment],
            [architecture.architecture_diagram],
            architecture.sequence_diagrams,
        ]
        return chain.from_iterable(groups)

    @staticmethod
    def _create_provider(settings: Settings) -> ArchitectureModelProvider:
        api_key = (
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise ArchitectureRecommendationNotConfiguredError(
                "OPENAI_API_KEY is required to generate architecture recommendations."
            )
        return OpenAIArchitectureProvider(
            api_key=api_key,
            model=settings.openai_architecture_model,
        )

