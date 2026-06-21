import hashlib
from datetime import UTC, datetime
from uuid import UUID

from app.agents.ambiguity import AmbiguityModelProvider, OpenAIAmbiguityProvider
from app.core.config import Settings
from app.core.exceptions import (
    AmbiguityDetectionError,
    AmbiguityDetectionNotConfiguredError,
)
from app.models.ambiguity import AmbiguityAnalysis, AmbiguityDetectionResult
from app.models.document import DocumentChunk
from app.models.requirements import Requirement, RequirementIntelligenceResult
from app.models.understanding import SpecificationUnderstandingResult
from app.services.ambiguity_store import AmbiguityDetectionStore
from app.services.chunks import ChunkService
from app.services.requirements import RequirementIntelligenceService
from app.services.understanding import SpecificationUnderstandingService

PROMPT_VERSION = "ambiguity-detection-v1"


class AmbiguityDetectionService:
    """Analyze every stored requirement for grounded ambiguity and gaps."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        understanding_service: SpecificationUnderstandingService | None = None,
        requirement_service: RequirementIntelligenceService | None = None,
        store: AmbiguityDetectionStore | None = None,
        provider: AmbiguityModelProvider | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_ambiguity_model
        self._chunk_service = chunk_service or ChunkService(settings)
        self._understanding_service = understanding_service or (
            SpecificationUnderstandingService(settings)
        )
        self._requirement_service = requirement_service or (
            RequirementIntelligenceService(settings)
        )
        self._store = store or AmbiguityDetectionStore(
            settings.understanding_cache_db
        )
        self._provider = provider

    def detect(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> AmbiguityDetectionResult:
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
                    cached=True,
                    analyzed_at=analyzed_at,
                )

        try:
            provider = self._provider or self._create_provider(self._settings)
            analysis = provider.analyze(context)
            self._validate_grounding(analysis, requirements.requirements, chunks)
        except AmbiguityDetectionError:
            raise
        except Exception as error:
            raise AmbiguityDetectionError(
                "The ambiguity detection model call failed."
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
            cached=False,
            analyzed_at=analyzed_at,
        )

    def _response(
        self,
        *,
        document_id: UUID,
        analysis: AmbiguityAnalysis,
        cached: bool,
        analyzed_at: datetime,
    ) -> AmbiguityDetectionResult:
        return AmbiguityDetectionResult(
            document_id=document_id,
            assessments=analysis.assessments,
            total_requirements=len(analysis.assessments),
            total_issues=sum(
                len(assessment.issues) for assessment in analysis.assessments
            ),
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
        analysis: AmbiguityAnalysis,
        requirements: list[Requirement],
        chunks: list[DocumentChunk],
    ) -> None:
        requirement_map = {
            requirement.requirement_id: requirement for requirement in requirements
        }
        assessment_ids = [
            assessment.requirement_id for assessment in analysis.assessments
        ]
        if len(assessment_ids) != len(set(assessment_ids)):
            raise AmbiguityDetectionError(
                "Each requirement must have exactly one ambiguity assessment."
            )
        if set(assessment_ids) != set(requirement_map):
            raise AmbiguityDetectionError(
                "Ambiguity analysis must assess every requirement exactly once."
            )

        valid_chunk_ids = {chunk.id for chunk in chunks}
        issue_ids: list[str] = []
        for assessment in analysis.assessments:
            requirement = requirement_map[assessment.requirement_id]
            if assessment.source_chunk != requirement.source_chunk:
                raise AmbiguityDetectionError(
                    "Assessment source chunks must match their requirements."
                )
            for issue in assessment.issues:
                issue_ids.append(issue.issue_id)
                if issue.requirement_id != assessment.requirement_id:
                    raise AmbiguityDetectionError(
                        "Issue requirement IDs must match their assessments."
                    )
                if (
                    issue.source_chunk != assessment.source_chunk
                    or issue.source_chunk not in valid_chunk_ids
                ):
                    raise AmbiguityDetectionError(
                        "Issues must reference their requirement's valid source chunk."
                    )
        if len(issue_ids) != len(set(issue_ids)):
            raise AmbiguityDetectionError(
                "Ambiguity issue IDs must be unique within a document."
            )

    @staticmethod
    def _create_provider(settings: Settings) -> AmbiguityModelProvider:
        api_key = (
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise AmbiguityDetectionNotConfiguredError(
                "OPENAI_API_KEY is required to run ambiguity detection."
            )
        return OpenAIAmbiguityProvider(
            api_key=api_key,
            model=settings.openai_ambiguity_model,
        )

