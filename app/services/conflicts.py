import hashlib
from datetime import UTC, datetime
from uuid import UUID

from app.agents.conflicts import ConflictModelProvider, OpenAIConflictProvider
from app.core.config import Settings
from app.core.exceptions import (
    ConflictDetectionError,
    ConflictDetectionNotConfiguredError,
)
from app.models.conflicts import ConflictAnalysis, ConflictDetectionResult
from app.models.document import DocumentChunk
from app.models.requirements import Requirement, RequirementIntelligenceResult
from app.models.understanding import SpecificationUnderstandingResult
from app.services.chunks import ChunkService
from app.services.conflict_store import ConflictDetectionStore
from app.services.requirements import RequirementIntelligenceService
from app.services.understanding import SpecificationUnderstandingService

PROMPT_VERSION = "conflict-detection-v1"


class ConflictDetectionService:
    """Find and persist grounded contradictions across requirements."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        understanding_service: SpecificationUnderstandingService | None = None,
        requirement_service: RequirementIntelligenceService | None = None,
        store: ConflictDetectionStore | None = None,
        provider: ConflictModelProvider | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_conflict_model
        self._chunk_service = chunk_service or ChunkService(settings)
        self._understanding_service = understanding_service or (
            SpecificationUnderstandingService(settings)
        )
        self._requirement_service = requirement_service or (
            RequirementIntelligenceService(settings)
        )
        self._store = store or ConflictDetectionStore(
            settings.understanding_cache_db
        )
        self._provider = provider

    def detect(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> ConflictDetectionResult:
        requirements = self._requirement_service.get_requirements(document_id)
        understanding = self._understanding_service.understand(document_id)
        chunks = self._chunk_service.get_chunks(document_id)
        context = self._assemble_context(
            document_id,
            understanding,
            requirements,
            chunks,
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
                analysis, analyzed_at = cached
                return self._response(
                    document_id=document_id,
                    analysis=analysis,
                    total_requirements=len(requirements.requirements),
                    cached=True,
                    analyzed_at=analyzed_at,
                )

        try:
            provider = self._provider or self._create_provider(self._settings)
            analysis = provider.analyze(context)
            self._validate_grounding(analysis, requirements.requirements, chunks)
        except ConflictDetectionError:
            raise
        except Exception as error:
            raise ConflictDetectionError(
                "The conflict detection model call failed."
            ) from error

        analyzed_at = datetime.now(UTC)
        self._store.set(
            document_id=document_id,
            fingerprint=fingerprint,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            result=analysis,
            analyzed_at=analyzed_at,
        )
        return self._response(
            document_id=document_id,
            analysis=analysis,
            total_requirements=len(requirements.requirements),
            cached=False,
            analyzed_at=analyzed_at,
        )

    def _response(
        self,
        *,
        document_id: UUID,
        analysis: ConflictAnalysis,
        total_requirements: int,
        cached: bool,
        analyzed_at: datetime,
    ) -> ConflictDetectionResult:
        return ConflictDetectionResult(
            document_id=document_id,
            conflicts=analysis.conflicts,
            total_requirements=total_requirements,
            total_conflicts=len(analysis.conflicts),
            cached=cached,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            analyzed_at=analyzed_at,
        )

    @staticmethod
    def _assemble_context(
        document_id: UUID,
        understanding: SpecificationUnderstandingResult,
        requirements: RequirementIntelligenceResult,
        chunks: list[DocumentChunk],
    ) -> str:
        source_chunks = {chunk.id: chunk for chunk in chunks}
        parts = [
            f"DOCUMENT_ID: {document_id}",
            "SPECIFICATION_UNDERSTANDING:",
            understanding.understanding.model_dump_json(indent=2),
            f"TOTAL_REQUIREMENTS: {len(requirements.requirements)}",
        ]
        for requirement in requirements.requirements:
            chunk = source_chunks.get(requirement.source_chunk)
            parts.append(
                "\n".join(
                    [
                        f"--- REQUIREMENT {requirement.requirement_id} ---",
                        f"TITLE: {requirement.title}",
                        f"CATEGORY: {requirement.category.value}",
                        f"PRIORITY: {requirement.priority.value}",
                        f"SOURCE_CHUNK: {requirement.source_chunk}",
                        f"REQUIREMENT: {requirement.description}",
                        "SOURCE_CONTEXT:",
                        chunk.text if chunk else "[source chunk unavailable]",
                    ]
                )
            )
        return "\n\n".join(parts)

    @staticmethod
    def _validate_grounding(
        analysis: ConflictAnalysis,
        requirements: list[Requirement],
        chunks: list[DocumentChunk],
    ) -> None:
        requirement_map = {
            requirement.requirement_id: requirement for requirement in requirements
        }
        valid_chunk_ids = {chunk.id for chunk in chunks}
        conflict_ids = [conflict.conflict_id for conflict in analysis.conflicts]
        if len(conflict_ids) != len(set(conflict_ids)):
            raise ConflictDetectionError(
                "Conflict IDs must be unique within a document."
            )

        for conflict in analysis.conflicts:
            evidence_requirement_ids = [
                evidence.requirement_id for evidence in conflict.evidence
            ]
            if len(set(evidence_requirement_ids)) < 2:
                raise ConflictDetectionError(
                    "Each conflict must reference at least two distinct requirements."
                )
            if any(
                requirement_id not in requirement_map
                for requirement_id in evidence_requirement_ids
            ):
                raise ConflictDetectionError(
                    "Conflict evidence referenced an unknown requirement."
                )

            expected_chunks = {
                requirement_map[requirement_id].source_chunk
                for requirement_id in evidence_requirement_ids
            }
            evidence_chunks = {
                evidence.source_chunk for evidence in conflict.evidence
            }
            supplied_chunks = set(conflict.source_chunks)
            if (
                len(supplied_chunks) < 2
                or supplied_chunks != evidence_chunks
                or evidence_chunks != expected_chunks
                or not supplied_chunks.issubset(valid_chunk_ids)
            ):
                raise ConflictDetectionError(
                    "Conflict source chunks must exactly match grounded evidence."
                )

    @staticmethod
    def _create_provider(settings: Settings) -> ConflictModelProvider:
        api_key = (
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise ConflictDetectionNotConfiguredError(
                "OPENAI_API_KEY is required to run conflict detection."
            )
        return OpenAIConflictProvider(
            api_key=api_key,
            model=settings.openai_conflict_model,
        )

