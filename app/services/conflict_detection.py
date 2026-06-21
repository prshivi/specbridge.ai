from __future__ import annotations

import hashlib
import json
from datetime import UTC
from uuid import UUID

from app.agents.conflict_detection import (
    ConflictDetectionAgent,
    FrameworkConflictProvider,
    OpenAIFrameworkConflictProvider,
)
from app.agents.framework import (
    AgentContext,
    AgentPipelineEngine,
    AgentRegistry,
    AgentResult,
)
from app.agents.framework.cache import AgentResultCache
from app.agents.framework.events import SQLiteAgentEventLogger
from app.agents.framework.pipeline import RetryPolicy
from app.core.config import Settings
from app.core.exceptions import (
    DetectedConflictsNotFoundError,
    DocumentChunksNotFoundError,
    FrameworkConflictDetectionError,
    FrameworkConflictNotConfiguredError,
    KnowledgeGraphNotFoundError,
)
from app.models.conflict_detection import (
    ConflictDetectionAgentResult,
    ConflictDetectionOutput,
    DetectedConflict,
)
from app.models.document import DocumentChunk
from app.models.knowledge import (
    EntityType,
    KnowledgeEntity,
    KnowledgeModel,
    KnowledgeRelationship,
    RelationshipType,
)
from app.models.requirement_extraction import RequirementExtractionResult
from app.services.chunks import ChunkService
from app.services.conflict_detection_store import FrameworkConflictStore
from app.services.knowledge import KnowledgeGraphService
from app.services.knowledge_store import KnowledgeGraphStore
from app.services.requirement_extraction import RequirementExtractionService
from app.services.specification_dna import SpecificationDNAService


class FrameworkConflictDetectionService:
    """Run, persist, retrieve, and graph-link ConflictDetectionAgent output."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        dna_service: SpecificationDNAService | None = None,
        requirement_service: RequirementExtractionService | None = None,
        knowledge_service: KnowledgeGraphService | None = None,
        knowledge_store: KnowledgeGraphStore | None = None,
        store: FrameworkConflictStore | None = None,
        provider: FrameworkConflictProvider | None = None,
        engine: AgentPipelineEngine | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_conflict_model
        self._chunk_service = chunk_service or ChunkService(settings)
        self._dna_service = dna_service or SpecificationDNAService(settings)
        self._requirement_service = requirement_service or (
            RequirementExtractionService(settings)
        )
        self._knowledge_service = knowledge_service or KnowledgeGraphService(settings)
        self._knowledge_store = knowledge_store or KnowledgeGraphStore(
            settings.understanding_cache_db
        )
        self._store = store or FrameworkConflictStore(settings.agent_framework_db)
        self._provider = provider
        self._agent = ConflictDetectionAgent(provider=provider)
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

    def run(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> ConflictDetectionAgentResult:
        chunks = self._chunk_service.get_chunks(document_id)
        if not chunks:
            raise DocumentChunksNotFoundError(
                "No parsed chunks were found for this document."
            )
        dna_result = self._dna_service.get(document_id)
        requirements = self._requirement_service.list(document_id)
        graph = self._get_or_build_graph(document_id)
        fingerprint = self._source_fingerprint(
            chunks,
            requirements,
            graph,
            dna_result.source_fingerprint,
        )
        if not force_refresh:
            stored = self._store.get_for_fingerprint(
                document_id=document_id,
                source_fingerprint=fingerprint,
                model=self._model,
                agent_version=self._agent.version,
            )
            if stored is not None:
                return stored

        provider = self._provider or self._create_provider()
        context = AgentContext(
            knowledge_graph=graph,
            specification_dna=dna_result.specification_dna,
            chunks=chunks,
            configuration={
                "source_fingerprint": fingerprint,
                "force_refresh": force_refresh,
            },
            llm_provider=provider,
            results={
                "requirement_extraction": AgentResult(
                    agent_name="requirement_extraction",
                    output={"requirements": [
                        item.model_dump(mode="json")
                        for item in requirements.requirements
                    ]},
                    confidence=1.0,
                    source_chunks=list(
                        dict.fromkeys(
                            chunk_id
                            for item in requirements.requirements
                            for chunk_id in item.source_chunk_ids
                        )
                    ),
                    cached=True,
                )
            },
        )
        try:
            agent_result = self._engine.execute_agent(self._agent.name, context)
            output = ConflictDetectionOutput.model_validate(agent_result.output)
            graph_updated = self._update_graph(
                document_id,
                output.conflicts,
                graph,
            )
        except FrameworkConflictDetectionError:
            raise
        except Exception as error:
            raise FrameworkConflictDetectionError(
                "The ConflictDetectionAgent model call failed."
            ) from error

        result = ConflictDetectionAgentResult(
            document_id=document_id,
            conflicts=output.conflicts,
            cached=agent_result.cached,
            model=self._model,
            agent_version=self._agent.version,
            source_fingerprint=fingerprint,
            execution_time_ms=agent_result.execution_time_ms,
            analyzed_at=agent_result.completed_at.astimezone(UTC),
            knowledge_graph_updated=graph_updated,
        )
        self._store.replace(result)
        return result

    def list(self, document_id: UUID) -> ConflictDetectionAgentResult:
        result = self._store.get_result(document_id)
        if result is None:
            raise DetectedConflictsNotFoundError(
                "Conflicts have not been analyzed for this document."
            )
        return result

    def get(self, document_id: UUID, conflict_id: str) -> DetectedConflict:
        conflict = self._store.get(document_id, conflict_id)
        if conflict is None:
            raise DetectedConflictsNotFoundError(
                f"Conflict '{conflict_id}' was not found for this document."
            )
        return conflict

    def _get_or_build_graph(self, document_id: UUID) -> KnowledgeModel:
        try:
            return self._knowledge_service.get(document_id)
        except KnowledgeGraphNotFoundError:
            self._knowledge_service.build(document_id)
            return self._knowledge_service.get(document_id)

    def _create_provider(self) -> FrameworkConflictProvider:
        api_key = (
            self._settings.openai_api_key.get_secret_value()
            if self._settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise FrameworkConflictNotConfiguredError(
                "OPENAI_API_KEY is required to run ConflictDetectionAgent."
            )
        return OpenAIFrameworkConflictProvider(
            api_key=api_key,
            model=self._model,
        )

    def _update_graph(
        self,
        document_id: UUID,
        conflicts: list[DetectedConflict],
        graph: KnowledgeModel,
    ) -> bool:
        entities: list[KnowledgeEntity] = []
        relationships: list[KnowledgeRelationship] = []
        requirement_nodes = {
            str(entity.metadata.get("requirement_id")): entity
            for entity in graph.entities
            if entity.entity_type is EntityType.REQUIREMENT
            and entity.metadata.get("requirement_id")
        }
        business_rule_nodes = {
            str(entity.metadata.get("explicit_id") or entity.title): entity
            for entity in graph.entities
            if entity.entity_type is EntityType.BUSINESS_RULE
        }
        for conflict in conflicts:
            conflict_id = (
                f"kg:{document_id}:conflict_issue:{conflict.conflict_id.casefold()}"
            )
            entities.append(
                KnowledgeEntity(
                    id=conflict_id,
                    document_id=document_id,
                    entity_type=EntityType.CONFLICT_ISSUE,
                    title=conflict.title,
                    description=conflict.description,
                    source_chunk_ids=conflict.source_chunk_ids,
                    confidence=conflict.confidence,
                    metadata={
                        "conflict_id": conflict.conflict_id,
                        "conflict_type": conflict.conflict_type.value,
                        "severity": conflict.severity.value,
                        "blocking_for_development": (
                            conflict.blocking_for_development
                        ),
                        "origin": "ConflictDetectionAgent",
                    },
                )
            )
            targets = [
                requirement_nodes[item]
                for item in conflict.involved_requirement_ids
                if item in requirement_nodes
            ]
            targets.extend(
                requirement_nodes[item]
                for item in conflict.involved_business_rule_ids
                if item in requirement_nodes
            )
            targets.extend(
                business_rule_nodes[item]
                for item in conflict.involved_business_rule_ids
                if item in business_rule_nodes
            )
            for target in {item.id: item for item in targets}.values():
                relationships.append(
                    KnowledgeRelationship(
                        id=self._relationship_id(conflict_id, target.id),
                        document_id=document_id,
                        source_id=conflict_id,
                        target_id=target.id,
                        relationship_type=RelationshipType.INVOLVES,
                        source_chunk_ids=list(
                            dict.fromkeys(
                                [
                                    *conflict.source_chunk_ids,
                                    *target.source_chunk_ids,
                                ]
                            )
                        ),
                        confidence=conflict.confidence,
                        metadata={"origin": "ConflictDetectionAgent"},
                    )
                )
        self._knowledge_store.upsert(
            document_id=document_id,
            entities=entities,
            relationships=relationships,
        )
        return True

    @staticmethod
    def _relationship_id(source_id: str, target_id: str) -> str:
        value = f"{source_id}|involves|{target_id}"
        return f"kgr:{hashlib.sha1(value.encode()).hexdigest()[:16]}"

    @staticmethod
    def _source_fingerprint(
        chunks: list[DocumentChunk],
        requirements: RequirementExtractionResult,
        graph: KnowledgeModel,
        dna_fingerprint: str,
    ) -> str:
        payload = {
            "dna_fingerprint": dna_fingerprint,
            "requirements_fingerprint": requirements.source_fingerprint,
            "requirements": [
                item.model_dump(mode="json") for item in requirements.requirements
            ],
            "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            "business_rules": [
                entity.model_dump(mode="json")
                for entity in graph.entities
                if entity.entity_type is EntityType.BUSINESS_RULE
            ],
            "workflow_constraints": [
                entity.model_dump(mode="json")
                for entity in graph.entities
                if entity.entity_type
                in {
                    EntityType.WORKFLOW,
                    EntityType.CONSTRAINT,
                    EntityType.VALIDATION,
                    EntityType.PERMISSION,
                    EntityType.INTEGRATION,
                    EntityType.DATA_ENTITY,
                }
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
