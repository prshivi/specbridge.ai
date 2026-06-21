import hashlib
from datetime import UTC, datetime
from uuid import UUID

from app.agents.requirements import OpenAIRequirementProvider, RequirementModelProvider
from app.core.config import Settings
from app.core.exceptions import (
    DocumentChunksNotFoundError,
    RequirementIntelligenceError,
    RequirementIntelligenceNotConfiguredError,
)
from app.models.document import DocumentChunk
from app.models.requirements import (
    RequirementIntelligence,
    RequirementIntelligenceResult,
)
from app.models.understanding import SpecificationUnderstandingResult
from app.services.chunks import ChunkService
from app.services.requirements_store import RequirementIntelligenceStore
from app.services.understanding import SpecificationUnderstandingService

PROMPT_VERSION = "requirement-intelligence-v1"


class RequirementIntelligenceService:
    """Extract, validate, store, and return traceable requirements."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        understanding_service: SpecificationUnderstandingService | None = None,
        store: RequirementIntelligenceStore | None = None,
        provider: RequirementModelProvider | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_requirements_model
        self._chunk_service = chunk_service or ChunkService(settings)
        self._understanding_service = understanding_service or (
            SpecificationUnderstandingService(settings)
        )
        self._store = store or RequirementIntelligenceStore(
            settings.understanding_cache_db
        )
        self._provider = provider

    def get_requirements(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> RequirementIntelligenceResult:
        chunks = self._chunk_service.get_chunks(document_id)
        if not chunks:
            raise DocumentChunksNotFoundError(
                "No parsed chunks were found for this document."
            )

        understanding = self._understanding_service.understand(document_id)
        context = self._assemble_context(document_id, understanding, chunks)
        fingerprint = hashlib.sha256(context.encode("utf-8")).hexdigest()
        if not force_refresh:
            cached = self._store.get(
                document_id=document_id,
                fingerprint=fingerprint,
                model=self._model,
                prompt_version=PROMPT_VERSION,
            )
            if cached:
                result, analyzed_at = cached
                return self._response(
                    document_id=document_id,
                    result=result,
                    cached=True,
                    analyzed_at=analyzed_at,
                )

        try:
            provider = self._provider or self._create_provider(self._settings)
            result = provider.analyze(context)
            self._validate_traceability(result, chunks)
        except RequirementIntelligenceError:
            raise
        except Exception as error:
            raise RequirementIntelligenceError(
                "The requirement intelligence model call failed."
            ) from error

        analyzed_at = datetime.now(UTC)
        self._store.set(
            document_id=document_id,
            fingerprint=fingerprint,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            result=result,
            analyzed_at=analyzed_at,
        )
        return self._response(
            document_id=document_id,
            result=result,
            cached=False,
            analyzed_at=analyzed_at,
        )

    def _response(
        self,
        *,
        document_id: UUID,
        result: RequirementIntelligence,
        cached: bool,
        analyzed_at: datetime,
    ) -> RequirementIntelligenceResult:
        return RequirementIntelligenceResult(
            document_id=document_id,
            requirements=result.requirements,
            cached=cached,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            analyzed_at=analyzed_at,
        )

    @staticmethod
    def _assemble_context(
        document_id: UUID,
        understanding: SpecificationUnderstandingResult,
        chunks: list[DocumentChunk],
    ) -> str:
        parts = [
            f"DOCUMENT_ID: {document_id}",
            "SPECIFICATION_UNDERSTANDING:",
            understanding.understanding.model_dump_json(indent=2),
            f"TOTAL_SOURCE_CHUNKS: {len(chunks)}",
        ]
        for chunk in chunks:
            parts.append(
                "\n".join(
                    [
                        f"--- SOURCE_CHUNK {chunk.id} ---",
                        f"CHUNK_NUMBER: {chunk.chunk_number}",
                        f"TYPE: {chunk.chunk_type.value}",
                        f"PAGE: {chunk.page or 'unknown'}",
                        f"SECTION: {chunk.section or 'unknown'}",
                        f"HEADING: {chunk.heading or 'unknown'}",
                        "CONTENT:",
                        chunk.text,
                    ]
                )
            )
        return "\n\n".join(parts)

    @staticmethod
    def _validate_traceability(
        result: RequirementIntelligence,
        chunks: list[DocumentChunk],
    ) -> None:
        valid_chunk_ids = {chunk.id for chunk in chunks}
        requirement_ids = [item.requirement_id for item in result.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise RequirementIntelligenceError(
                "Requirement IDs must be unique within a document."
            )
        invalid_sources = sorted(
            {
                item.source_chunk
                for item in result.requirements
                if item.source_chunk not in valid_chunk_ids
            }
        )
        if invalid_sources:
            raise RequirementIntelligenceError(
                "Requirements referenced unknown source chunks: "
                + ", ".join(invalid_sources)
            )

    @staticmethod
    def _create_provider(settings: Settings) -> RequirementModelProvider:
        api_key = (
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise RequirementIntelligenceNotConfiguredError(
                "OPENAI_API_KEY is required to run requirement intelligence."
            )
        return OpenAIRequirementProvider(
            api_key=api_key,
            model=settings.openai_requirements_model,
        )

