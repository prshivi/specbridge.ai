from __future__ import annotations

import hashlib
import json
from datetime import UTC
from uuid import UUID

from app.agents.framework import (
    AgentContext,
    AgentPipelineEngine,
    AgentRegistry,
    AgentResult,
)
from app.agents.framework.cache import AgentResultCache
from app.agents.framework.events import SQLiteAgentEventLogger
from app.agents.framework.pipeline import RetryPolicy
from app.agents.missing_requirement_detection import (
    MissingRequirementDetectionAgent,
    MissingRequirementProvider,
    OpenAIMissingRequirementProvider,
)
from app.core.config import Settings
from app.core.exceptions import (
    DetectedConflictsNotFoundError,
    DocumentChunksNotFoundError,
    ExtractedRequirementsNotFoundError,
    KnowledgeGraphNotFoundError,
    MissingRequirementDetectionError,
    MissingRequirementIssuesNotFoundError,
    MissingRequirementNotConfiguredError,
)
from app.models.conflict_detection import ConflictDetectionAgentResult
from app.models.document import DocumentChunk
from app.models.knowledge import (
    EntityType,
    KnowledgeEntity,
    KnowledgeModel,
    KnowledgeRelationship,
    RelationshipType,
)
from app.models.missing_requirements import (
    MissingRequirementDetectionOutput,
    MissingRequirementDetectionResult,
    MissingRequirementGapType,
    MissingRequirementIssue,
)
from app.models.requirement_extraction import RequirementExtractionResult
from app.services.chunks import ChunkService
from app.services.conflict_detection import FrameworkConflictDetectionService
from app.services.knowledge import KnowledgeGraphService
from app.services.knowledge_store import KnowledgeGraphStore
from app.services.missing_requirement_store import MissingRequirementStore
from app.services.requirement_extraction import RequirementExtractionService
from app.services.specification_dna import SpecificationDNAService


class MissingRequirementDetectionService:
    """Execute, store, retrieve, and graph-link contextual requirement gaps."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        dna_service: SpecificationDNAService | None = None,
        requirement_service: RequirementExtractionService | None = None,
        conflict_service: FrameworkConflictDetectionService | None = None,
        knowledge_service: KnowledgeGraphService | None = None,
        knowledge_store: KnowledgeGraphStore | None = None,
        store: MissingRequirementStore | None = None,
        provider: MissingRequirementProvider | None = None,
        engine: AgentPipelineEngine | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_missing_requirements_model
        self._chunk_service = chunk_service or ChunkService(settings)
        self._dna_service = dna_service or SpecificationDNAService(settings)
        self._requirement_service = requirement_service or (
            RequirementExtractionService(settings)
        )
        self._conflict_service = conflict_service or (
            FrameworkConflictDetectionService(settings)
        )
        self._knowledge_service = knowledge_service or KnowledgeGraphService(settings)
        self._knowledge_store = knowledge_store or KnowledgeGraphStore(
            settings.understanding_cache_db
        )
        self._store = store or MissingRequirementStore(settings.agent_framework_db)
        self._provider = provider
        self._agent = MissingRequirementDetectionAgent(provider=provider)
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
    ) -> MissingRequirementDetectionResult:
        chunks = self._chunk_service.get_chunks(document_id)
        if not chunks:
            raise DocumentChunksNotFoundError(
                "No parsed chunks were found for this document."
            )
        dna_result = self._dna_service.get(document_id)
        requirements = self._requirement_service.list(document_id)
        conflicts = self._conflict_service.list(document_id)
        graph = self._get_or_build_graph(document_id)
        fingerprint = self._source_fingerprint(
            chunks,
            requirements,
            conflicts,
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
                    output={
                        "requirements": [
                            item.model_dump(mode="json")
                            for item in requirements.requirements
                        ]
                    },
                    confidence=1.0,
                    cached=True,
                ),
                "conflict_detection": AgentResult(
                    agent_name="conflict_detection",
                    output={
                        "conflicts": [
                            item.model_dump(mode="json")
                            for item in conflicts.conflicts
                        ]
                    },
                    confidence=1.0,
                    cached=True,
                ),
            },
        )
        try:
            agent_result = self._engine.execute_agent(self._agent.name, context)
            output = MissingRequirementDetectionOutput.model_validate(
                agent_result.output
            )
            graph_updated, integration_links = self._update_graph(
                document_id,
                output.missing_requirements,
                graph,
            )
        except MissingRequirementDetectionError:
            raise
        except Exception as error:
            raise MissingRequirementDetectionError(
                "The MissingRequirementDetectionAgent model call failed."
            ) from error

        result = MissingRequirementDetectionResult(
            document_id=document_id,
            missing_requirements=output.missing_requirements,
            cached=agent_result.cached,
            model=self._model,
            agent_version=self._agent.version,
            source_fingerprint=fingerprint,
            execution_time_ms=agent_result.execution_time_ms,
            analyzed_at=agent_result.completed_at.astimezone(UTC),
            knowledge_graph_updated=graph_updated,
        )
        self._store.replace(result, integration_links=integration_links)
        return result

    def list(self, document_id: UUID) -> MissingRequirementDetectionResult:
        result = self._store.get_result(document_id)
        if result is None:
            raise MissingRequirementIssuesNotFoundError(
                "Missing requirements have not been analyzed for this document."
            )
        return result

    def get(
        self,
        document_id: UUID,
        missing_requirement_id: str,
    ) -> MissingRequirementIssue:
        issue = self._store.get(document_id, missing_requirement_id)
        if issue is None:
            raise MissingRequirementIssuesNotFoundError(
                f"Missing requirement '{missing_requirement_id}' was not found "
                "for this document."
            )
        return issue

    def _get_or_build_graph(self, document_id: UUID) -> KnowledgeModel:
        try:
            return self._knowledge_service.get(document_id)
        except KnowledgeGraphNotFoundError:
            self._knowledge_service.build(document_id)
            return self._knowledge_service.get(document_id)

    def _create_provider(self) -> MissingRequirementProvider:
        api_key = (
            self._settings.openai_api_key.get_secret_value()
            if self._settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise MissingRequirementNotConfiguredError(
                "OPENAI_API_KEY is required to run "
                "MissingRequirementDetectionAgent."
            )
        return OpenAIMissingRequirementProvider(
            api_key=api_key,
            model=self._model,
        )

    def _update_graph(
        self,
        document_id: UUID,
        issues: list[MissingRequirementIssue],
        graph: KnowledgeModel,
    ) -> tuple[bool, dict[str, list[str]]]:
        entities: list[KnowledgeEntity] = []
        relationships: list[KnowledgeRelationship] = []
        requirement_nodes = self._indexed_entities(
            graph, EntityType.REQUIREMENT, ("requirement_id",)
        )
        workflow_nodes = self._indexed_entities(
            graph, EntityType.WORKFLOW, ("workflow_id", "explicit_id")
        )
        actor_nodes = self._indexed_entities(
            graph, EntityType.ACTOR, ("actor_id", "explicit_id")
        )
        integration_nodes = [
            entity
            for entity in graph.entities
            if entity.entity_type is EntityType.INTEGRATION
        ]
        integration_links: dict[str, list[str]] = {}

        for issue in issues:
            issue_node_id = (
                f"kg:{document_id}:missing_requirement_issue:"
                f"{issue.missing_requirement_id.casefold()}"
            )
            entities.append(
                KnowledgeEntity(
                    id=issue_node_id,
                    document_id=document_id,
                    entity_type=EntityType.MISSING_REQUIREMENT_ISSUE,
                    title=issue.title,
                    description=issue.description,
                    source_chunk_ids=issue.source_chunk_ids,
                    confidence=issue.confidence,
                    metadata={
                        "missing_requirement_id": issue.missing_requirement_id,
                        "gap_type": issue.gap_type.value,
                        "severity": issue.severity.value,
                        "blocking_for_development": (
                            issue.blocking_for_development
                        ),
                        "explicit_gap_or_inferred_gap": (
                            issue.explicit_gap_or_inferred_gap.value
                        ),
                        "origin": "MissingRequirementDetectionAgent",
                    },
                )
            )
            targets: list[KnowledgeEntity] = []
            targets.extend(
                requirement_nodes[item]
                for item in issue.related_requirement_ids
                if item in requirement_nodes
            )
            targets.extend(
                workflow_nodes[item]
                for item in issue.related_workflow_ids
                if item in workflow_nodes
            )
            targets.extend(
                actor_nodes[item]
                for item in issue.related_actor_ids
                if item in actor_nodes
            )
            relevant_integrations = self._related_integrations(
                issue, integration_nodes
            )
            integration_links[issue.missing_requirement_id] = [
                entity.id for entity in relevant_integrations
            ]
            targets.extend(relevant_integrations)

            for target in {entity.id: entity for entity in targets}.values():
                relationships.append(
                    KnowledgeRelationship(
                        id=self._relationship_id(issue_node_id, target.id),
                        document_id=document_id,
                        source_id=issue_node_id,
                        target_id=target.id,
                        relationship_type=RelationshipType.RELATED_TO,
                        source_chunk_ids=list(
                            dict.fromkeys(
                                [*issue.source_chunk_ids, *target.source_chunk_ids]
                            )
                        ),
                        confidence=issue.confidence,
                        metadata={
                            "origin": "MissingRequirementDetectionAgent"
                        },
                    )
                )
        self._knowledge_store.upsert(
            document_id=document_id,
            entities=entities,
            relationships=relationships,
        )
        return True, integration_links

    @staticmethod
    def _indexed_entities(
        graph: KnowledgeModel,
        entity_type: EntityType,
        metadata_keys: tuple[str, ...],
    ) -> dict[str, KnowledgeEntity]:
        result: dict[str, KnowledgeEntity] = {}
        for entity in graph.entities:
            if entity.entity_type is not entity_type:
                continue
            result[entity.id] = entity
            result[entity.title] = entity
            for key in metadata_keys:
                if entity.metadata.get(key):
                    result[str(entity.metadata[key])] = entity
        return result

    @staticmethod
    def _related_integrations(
        issue: MissingRequirementIssue,
        integrations: list[KnowledgeEntity],
    ) -> list[KnowledgeEntity]:
        source_chunks = set(issue.source_chunk_ids)
        overlapping = [
            entity
            for entity in integrations
            if source_chunks & set(entity.source_chunk_ids)
        ]
        if overlapping:
            return overlapping
        if (
            issue.gap_type
            is MissingRequirementGapType.INTEGRATION_FAILURE_HANDLING
            and len(integrations) == 1
        ):
            return integrations
        return []

    @staticmethod
    def _relationship_id(source_id: str, target_id: str) -> str:
        value = f"{source_id}|related_to|{target_id}"
        return f"kgr:{hashlib.sha1(value.encode()).hexdigest()[:16]}"

    @staticmethod
    def _source_fingerprint(
        chunks: list[DocumentChunk],
        requirements: RequirementExtractionResult,
        conflicts: ConflictDetectionAgentResult,
        graph: KnowledgeModel,
        dna_fingerprint: str,
    ) -> str:
        graph_entities = [
            entity.model_dump(mode="json")
            for entity in graph.entities
            if entity.entity_type
            is not EntityType.MISSING_REQUIREMENT_ISSUE
        ]
        graph_relationships = [
            relationship.model_dump(mode="json")
            for relationship in graph.relationships
            if relationship.metadata.get("origin")
            != "MissingRequirementDetectionAgent"
        ]
        payload = {
            "dna_fingerprint": dna_fingerprint,
            "requirements_fingerprint": requirements.source_fingerprint,
            "conflicts_fingerprint": conflicts.source_fingerprint,
            "requirements": [
                item.model_dump(mode="json") for item in requirements.requirements
            ],
            "conflicts": [
                item.model_dump(mode="json") for item in conflicts.conflicts
            ],
            "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            "graph_entities": graph_entities,
            "graph_relationships": graph_relationships,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
