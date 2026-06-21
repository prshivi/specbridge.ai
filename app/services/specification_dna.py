import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from app.agents.framework import AgentContext, AgentPipelineEngine, AgentRegistry
from app.agents.framework.cache import AgentResultCache
from app.agents.framework.events import SQLiteAgentEventLogger
from app.agents.framework.pipeline import RetryPolicy
from app.agents.specification_dna import (
    OpenAISpecificationDNAProvider,
    SpecificationDNAProvider,
    SpecificationUnderstandingAgent,
)
from app.core.config import Settings
from app.core.exceptions import (
    DocumentChunksNotFoundError,
    KnowledgeGraphNotFoundError,
    UnderstandingAgentError,
    UnderstandingAgentNotConfiguredError,
)
from app.models.document import DocumentChunk
from app.models.knowledge import KnowledgeModel
from app.models.specification_dna import (
    SpecificationDNA,
    SpecificationDNAResult,
)
from app.services.chunks import ChunkService
from app.services.knowledge import KnowledgeGraphService
from app.services.specification_dna_store import SpecificationDNAStore


class SpecificationDNAService:
    """Run the framework-based understanding agent and persist its DNA."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        knowledge_service: KnowledgeGraphService | None = None,
        store: SpecificationDNAStore | None = None,
        provider: SpecificationDNAProvider | None = None,
        engine: AgentPipelineEngine | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_understanding_model
        self._chunk_service = chunk_service or ChunkService(settings)
        self._knowledge_service = knowledge_service or KnowledgeGraphService(settings)
        self._store = store or SpecificationDNAStore(settings.agent_framework_db)
        self._provider = provider
        self._agent = SpecificationUnderstandingAgent(provider=provider)
        if engine is None:
            registry = AgentRegistry()
            registry.register(self._agent)
            engine = AgentPipelineEngine(
                registry,
                cache=AgentResultCache(settings.agent_framework_db),
                event_logger=SQLiteAgentEventLogger(settings.agent_framework_db),
                default_retry_policy=RetryPolicy(
                    max_attempts=settings.agent_retry_attempts,
                    initial_delay_seconds=settings.agent_retry_delay_seconds,
                ),
            )
        self._engine = engine

    def get(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> SpecificationDNAResult:
        chunks = self._chunk_service.get_chunks(document_id)
        if not chunks:
            raise DocumentChunksNotFoundError(
                "No parsed chunks were found for this document."
            )
        knowledge_graph = self._get_or_build_knowledge_graph(document_id)
        source_fingerprint = self._source_fingerprint(chunks, knowledge_graph)
        if not force_refresh:
            stored = self._store.get(
                document_id=document_id,
                source_fingerprint=source_fingerprint,
                model=self._model,
                agent_version=self._agent.version,
            )
            if stored is not None:
                return stored

        provider = self._provider or self._create_provider()
        context = AgentContext(
            knowledge_graph=knowledge_graph,
            chunks=chunks,
            configuration={
                "source_fingerprint": source_fingerprint,
                "force_refresh": force_refresh,
                "model": self._model,
            },
            llm_provider=provider,
        )
        try:
            agent_result = self._engine.execute_agent(self._agent.name, context)
            dna = SpecificationDNA.model_validate(agent_result.output)
        except UnderstandingAgentError:
            raise
        except Exception as error:
            raise UnderstandingAgentError(
                "The Specification DNA model call failed."
            ) from error

        result = SpecificationDNAResult(
            document_id=document_id,
            specification_dna=dna,
            cached=agent_result.cached,
            model=self._model,
            agent_version=self._agent.version,
            source_fingerprint=source_fingerprint,
            execution_time_ms=agent_result.execution_time_ms,
            generated_at=agent_result.completed_at.astimezone(UTC),
        )
        self._store.set(result)
        return result

    def _get_or_build_knowledge_graph(self, document_id: UUID) -> KnowledgeModel:
        try:
            return self._knowledge_service.get(document_id)
        except KnowledgeGraphNotFoundError:
            self._knowledge_service.build(document_id)
            return self._knowledge_service.get(document_id)

    def _create_provider(self) -> SpecificationDNAProvider:
        api_key = (
            self._settings.openai_api_key.get_secret_value()
            if self._settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise UnderstandingAgentNotConfiguredError(
                "OPENAI_API_KEY is required to generate Specification DNA."
            )
        return OpenAISpecificationDNAProvider(
            api_key=api_key,
            model=self._model,
        )

    @staticmethod
    def _source_fingerprint(
        chunks: list[DocumentChunk],
        knowledge_graph: KnowledgeModel,
    ) -> str:
        payload = {
            "chunks": [
                chunk.model_dump(mode="json")
                for chunk in sorted(chunks, key=lambda item: item.chunk_number)
            ],
            "knowledge_graph": knowledge_graph.model_dump(
                mode="json",
                exclude={"built_at"},
            ),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
