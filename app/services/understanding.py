import hashlib
from datetime import UTC, datetime
from uuid import UUID

from app.agents.understanding import (
    OpenAIUnderstandingProvider,
    UnderstandingModelProvider,
)
from app.core.config import Settings
from app.core.exceptions import (
    DocumentChunksNotFoundError,
    UnderstandingAgentError,
    UnderstandingAgentNotConfiguredError,
)
from app.models.document import DocumentChunk
from app.models.understanding import SpecificationUnderstandingResult
from app.services.chunks import ChunkService
from app.services.understanding_cache import UnderstandingCache

PROMPT_VERSION = "specification-understanding-v1"


class SpecificationUnderstandingService:
    """Run and cache one whole-document specification understanding pass."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        cache: UnderstandingCache | None = None,
        provider: UnderstandingModelProvider | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_understanding_model
        self._chunk_service = chunk_service or ChunkService(settings)
        self._cache = cache or UnderstandingCache(settings.understanding_cache_db)
        self._provider = provider

    def understand(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> SpecificationUnderstandingResult:
        chunks = self._chunk_service.get_chunks(document_id)
        if not chunks:
            raise DocumentChunksNotFoundError(
                "No parsed chunks were found for this document."
            )

        context = self._assemble_context(document_id, chunks)
        fingerprint = hashlib.sha256(context.encode("utf-8")).hexdigest()
        if not force_refresh:
            cached = self._cache.get(
                document_id=document_id,
                fingerprint=fingerprint,
                model=self._model,
                prompt_version=PROMPT_VERSION,
            )
            if cached:
                understanding, analyzed_at = cached
                return SpecificationUnderstandingResult(
                    document_id=document_id,
                    understanding=understanding,
                    cached=True,
                    model=self._model,
                    prompt_version=PROMPT_VERSION,
                    analyzed_at=analyzed_at,
                )

        try:
            provider = self._provider or self._create_provider(self._settings)
            understanding = provider.analyze(context)
        except UnderstandingAgentError:
            raise
        except Exception as error:
            raise UnderstandingAgentError(
                "The specification understanding model call failed."
            ) from error

        analyzed_at = datetime.now(UTC)
        self._cache.set(
            document_id=document_id,
            fingerprint=fingerprint,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            result=understanding,
            analyzed_at=analyzed_at,
        )
        return SpecificationUnderstandingResult(
            document_id=document_id,
            understanding=understanding,
            cached=False,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            analyzed_at=analyzed_at,
        )

    @staticmethod
    def _assemble_context(document_id: UUID, chunks: list[DocumentChunk]) -> str:
        parts = [
            f"DOCUMENT_ID: {document_id}",
            f"TOTAL_CHUNKS: {len(chunks)}",
        ]
        for chunk in chunks:
            parts.append(
                "\n".join(
                    [
                        f"--- CHUNK {chunk.chunk_number} ---",
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
    def _create_provider(settings: Settings) -> UnderstandingModelProvider:
        api_key = (
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise UnderstandingAgentNotConfiguredError(
                "OPENAI_API_KEY is required to run specification understanding."
            )
        return OpenAIUnderstandingProvider(
            api_key=api_key,
            model=settings.openai_understanding_model,
        )
