from __future__ import annotations

import hashlib
import json
from datetime import UTC
from uuid import UUID

from app.agents.assumption_ledger import (
    AssumptionLedgerAgent,
    AssumptionLedgerProvider,
    OpenAIAssumptionLedgerProvider,
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
    AssumptionLedgerError,
    AssumptionLedgerNotConfiguredError,
    AssumptionLedgerNotFoundError,
    DocumentChunksNotFoundError,
    KnowledgeGraphNotFoundError,
)
from app.models.ambiguity import AmbiguityDetectionResult
from app.models.assumption_ledger import (
    AssumptionLedgerOutput,
    AssumptionStatus,
    FrameworkAssumptionLedgerResult,
    LedgerAssumption,
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
from app.models.missing_requirements import MissingRequirementDetectionResult
from app.models.requirement_extraction import RequirementExtractionResult
from app.services.ambiguity import AmbiguityDetectionService
from app.services.assumption_ledger_store import FrameworkAssumptionLedgerStore
from app.services.chunks import ChunkService
from app.services.conflict_detection import FrameworkConflictDetectionService
from app.services.knowledge import KnowledgeGraphService
from app.services.knowledge_store import KnowledgeGraphStore
from app.services.missing_requirement_detection import (
    MissingRequirementDetectionService,
)
from app.services.requirement_extraction import RequirementExtractionService
from app.services.specification_dna import SpecificationDNAService


class FrameworkAssumptionLedgerService:
    """Execute, persist, retrieve, and graph-link the framework ledger."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        dna_service: SpecificationDNAService | None = None,
        requirement_service: RequirementExtractionService | None = None,
        ambiguity_service: AmbiguityDetectionService | None = None,
        conflict_service: FrameworkConflictDetectionService | None = None,
        missing_service: MissingRequirementDetectionService | None = None,
        knowledge_service: KnowledgeGraphService | None = None,
        knowledge_store: KnowledgeGraphStore | None = None,
        store: FrameworkAssumptionLedgerStore | None = None,
        provider: AssumptionLedgerProvider | None = None,
        engine: AgentPipelineEngine | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_assumption_model
        self._chunk_service = chunk_service or ChunkService(settings)
        self._dna_service = dna_service or SpecificationDNAService(settings)
        self._requirement_service = requirement_service or (
            RequirementExtractionService(settings)
        )
        self._ambiguity_service = ambiguity_service or AmbiguityDetectionService(
            settings
        )
        self._conflict_service = conflict_service or (
            FrameworkConflictDetectionService(settings)
        )
        self._missing_service = missing_service or (
            MissingRequirementDetectionService(settings)
        )
        self._knowledge_service = knowledge_service or KnowledgeGraphService(settings)
        self._knowledge_store = knowledge_store or KnowledgeGraphStore(
            settings.understanding_cache_db
        )
        self._store = store or FrameworkAssumptionLedgerStore(
            settings.agent_framework_db
        )
        self._provider = provider
        self._agent = AssumptionLedgerAgent(provider=provider)
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
    ) -> FrameworkAssumptionLedgerResult:
        chunks = self._chunk_service.get_chunks(document_id)
        if not chunks:
            raise DocumentChunksNotFoundError(
                "No parsed chunks were found for this document."
            )
        dna = self._dna_service.get(document_id)
        requirements = self._requirement_service.list(document_id)
        ambiguities = self._ambiguity_service.detect(document_id)
        conflicts = self._conflict_service.list(document_id)
        missing = self._missing_service.list(document_id)
        graph = self._get_or_build_graph(document_id)
        fingerprint = self._source_fingerprint(
            chunks,
            dna.source_fingerprint,
            requirements,
            ambiguities,
            conflicts,
            missing,
            graph,
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
            specification_dna=dna.specification_dna,
            chunks=chunks,
            configuration={
                "source_fingerprint": fingerprint,
                "force_refresh": force_refresh,
            },
            llm_provider=provider,
            results={
                "requirement_extraction": self._dependency_result(
                    "requirement_extraction",
                    {
                        "requirements": [
                            item.model_dump(mode="json")
                            for item in requirements.requirements
                        ]
                    },
                ),
                "ambiguity_detection": self._dependency_result(
                    "ambiguity_detection",
                    ambiguities.model_dump(mode="json"),
                ),
                "conflict_detection": self._dependency_result(
                    "conflict_detection",
                    {
                        "conflicts": [
                            item.model_dump(mode="json")
                            for item in conflicts.conflicts
                        ]
                    },
                ),
                "missing_requirement_detection": self._dependency_result(
                    "missing_requirement_detection",
                    {
                        "missing_requirements": [
                            item.model_dump(mode="json")
                            for item in missing.missing_requirements
                        ]
                    },
                ),
            },
        )
        try:
            agent_result = self._engine.execute_agent(self._agent.name, context)
            output = AssumptionLedgerOutput.model_validate(agent_result.output)
            graph_updated = self._update_graph(
                document_id,
                output.assumptions,
                ambiguities,
                graph,
            )
        except AssumptionLedgerError:
            raise
        except Exception as error:
            raise AssumptionLedgerError(
                "The AssumptionLedgerAgent model call failed."
            ) from error

        result = FrameworkAssumptionLedgerResult(
            document_id=document_id,
            facts=output.facts,
            assumptions=output.assumptions,
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

    def list(self, document_id: UUID) -> FrameworkAssumptionLedgerResult:
        result = self._store.get_result(document_id)
        if result is None:
            raise AssumptionLedgerNotFoundError(
                "The assumption ledger has not been generated for this document."
            )
        return result

    def get(self, document_id: UUID, assumption_id: str) -> LedgerAssumption:
        assumption = self._store.get(document_id, assumption_id)
        if assumption is None:
            raise AssumptionLedgerNotFoundError(
                f"Assumption '{assumption_id}' was not found for this document."
            )
        return assumption

    def update_status(
        self,
        document_id: UUID,
        assumption_id: str,
        status: AssumptionStatus,
    ) -> LedgerAssumption:
        assumption = self._store.update_status(
            document_id,
            assumption_id,
            status,
        )
        if assumption is None:
            raise AssumptionLedgerNotFoundError(
                f"Assumption '{assumption_id}' was not found for this document."
            )
        self._update_graph_status(document_id, assumption)
        return assumption

    def _get_or_build_graph(self, document_id: UUID) -> KnowledgeModel:
        try:
            return self._knowledge_service.get(document_id)
        except KnowledgeGraphNotFoundError:
            self._knowledge_service.build(document_id)
            return self._knowledge_service.get(document_id)

    def _create_provider(self) -> AssumptionLedgerProvider:
        api_key = (
            self._settings.openai_api_key.get_secret_value()
            if self._settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise AssumptionLedgerNotConfiguredError(
                "OPENAI_API_KEY is required to run AssumptionLedgerAgent."
            )
        return OpenAIAssumptionLedgerProvider(
            api_key=api_key,
            model=self._model,
        )

    @staticmethod
    def _dependency_result(name: str, output: object) -> AgentResult:
        return AgentResult(
            agent_name=name,
            output=output,
            confidence=1.0,
            cached=True,
        )

    def _update_graph(
        self,
        document_id: UUID,
        assumptions: list[LedgerAssumption],
        ambiguities: AmbiguityDetectionResult,
        graph: KnowledgeModel,
    ) -> bool:
        entities: list[KnowledgeEntity] = []
        relationships: list[KnowledgeRelationship] = []
        indexes = {
            EntityType.REQUIREMENT: self._indexed_entities(
                graph, EntityType.REQUIREMENT, ("requirement_id",)
            ),
            EntityType.CONFLICT_ISSUE: self._indexed_entities(
                graph, EntityType.CONFLICT_ISSUE, ("conflict_id",)
            ),
            EntityType.MISSING_REQUIREMENT_ISSUE: self._indexed_entities(
                graph,
                EntityType.MISSING_REQUIREMENT_ISSUE,
                ("missing_requirement_id",),
            ),
        }
        ambiguity_nodes: dict[str, KnowledgeEntity] = {}
        for assessment in ambiguities.assessments:
            for issue in assessment.issues:
                node = KnowledgeEntity(
                    id=(
                        f"kg:{document_id}:ambiguity_issue:"
                        f"{issue.issue_id.casefold()}"
                    ),
                    document_id=document_id,
                    entity_type=EntityType.AMBIGUITY_ISSUE,
                    title=issue.issue_type.value.replace("_", " ").title(),
                    description=issue.reason,
                    source_chunk_ids=[issue.source_chunk],
                    confidence=issue.confidence,
                    metadata={
                        "ambiguity_id": issue.issue_id,
                        "requirement_id": issue.requirement_id,
                        "severity": issue.severity.value,
                        "origin": "AmbiguityDetectionAgent",
                    },
                )
                entities.append(node)
                ambiguity_nodes[issue.issue_id] = node

        contextual_entities = [
            entity
            for entity in graph.entities
            if entity.entity_type
            in {
                EntityType.ACTOR,
                EntityType.WORKFLOW,
                EntityType.INTEGRATION,
                EntityType.BUSINESS_RULE,
                EntityType.VALIDATION,
                EntityType.PERMISSION,
            }
        ]
        for assumption in assumptions:
            node_id = (
                f"kg:{document_id}:assumption:"
                f"{assumption.assumption_id.casefold()}"
            )
            node = self._assumption_entity(document_id, node_id, assumption)
            entities.append(node)
            targets: list[KnowledgeEntity] = []
            targets.extend(
                indexes[EntityType.REQUIREMENT][item]
                for item in assumption.related_requirement_ids
                if item in indexes[EntityType.REQUIREMENT]
            )
            targets.extend(
                ambiguity_nodes[item]
                for item in assumption.related_ambiguity_ids
                if item in ambiguity_nodes
            )
            targets.extend(
                indexes[EntityType.CONFLICT_ISSUE][item]
                for item in assumption.related_conflict_ids
                if item in indexes[EntityType.CONFLICT_ISSUE]
            )
            targets.extend(
                indexes[EntityType.MISSING_REQUIREMENT_ISSUE][item]
                for item in assumption.related_missing_requirement_ids
                if item in indexes[EntityType.MISSING_REQUIREMENT_ISSUE]
            )
            targets.extend(
                entity
                for entity in contextual_entities
                if set(assumption.source_chunk_ids)
                & set(entity.source_chunk_ids)
            )
            for target in {item.id: item for item in targets}.values():
                relationships.append(
                    KnowledgeRelationship(
                        id=self._relationship_id(node_id, target.id),
                        document_id=document_id,
                        source_id=node_id,
                        target_id=target.id,
                        relationship_type=RelationshipType.RELATED_TO,
                        source_chunk_ids=list(
                            dict.fromkeys(
                                [
                                    *assumption.source_chunk_ids,
                                    *target.source_chunk_ids,
                                ]
                            )
                        ),
                        confidence=assumption.confidence,
                        metadata={"origin": "AssumptionLedgerAgent"},
                    )
                )
        self._knowledge_store.upsert(
            document_id=document_id,
            entities=entities,
            relationships=relationships,
        )
        return True

    def _update_graph_status(
        self,
        document_id: UUID,
        assumption: LedgerAssumption,
    ) -> None:
        node_id = (
            f"kg:{document_id}:assumption:{assumption.assumption_id.casefold()}"
        )
        self._knowledge_store.upsert(
            document_id=document_id,
            entities=[self._assumption_entity(document_id, node_id, assumption)],
            relationships=[],
        )

    @staticmethod
    def _assumption_entity(
        document_id: UUID,
        node_id: str,
        assumption: LedgerAssumption,
    ) -> KnowledgeEntity:
        return KnowledgeEntity(
            id=node_id,
            document_id=document_id,
            entity_type=EntityType.ASSUMPTION,
            title=assumption.title,
            description=assumption.description,
            source_chunk_ids=assumption.source_chunk_ids,
            confidence=assumption.confidence,
            metadata={
                "assumption_id": assumption.assumption_id,
                "assumption_type": assumption.assumption_type.value,
                "impact_area": assumption.impact_area.value,
                "risk_level": assumption.risk_level.value,
                "status": assumption.status.value,
                "needs_stakeholder_confirmation": (
                    assumption.needs_stakeholder_confirmation
                ),
                "origin": "AssumptionLedgerAgent",
            },
        )

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
    def _relationship_id(source_id: str, target_id: str) -> str:
        value = f"{source_id}|related_to|{target_id}"
        return f"kgr:{hashlib.sha1(value.encode()).hexdigest()[:16]}"

    @staticmethod
    def _source_fingerprint(
        chunks: list[DocumentChunk],
        dna_fingerprint: str,
        requirements: RequirementExtractionResult,
        ambiguities: AmbiguityDetectionResult,
        conflicts: ConflictDetectionAgentResult,
        missing: MissingRequirementDetectionResult,
        graph: KnowledgeModel,
    ) -> str:
        payload = {
            "dna_fingerprint": dna_fingerprint,
            "requirements": requirements.model_dump(mode="json"),
            "ambiguities": ambiguities.model_dump(mode="json"),
            "conflicts": conflicts.model_dump(mode="json"),
            "missing_requirements": missing.model_dump(mode="json"),
            "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            "graph_entities": [
                entity.model_dump(mode="json")
                for entity in graph.entities
                if entity.entity_type is not EntityType.ASSUMPTION
            ],
            "graph_relationships": [
                relationship.model_dump(mode="json")
                for relationship in graph.relationships
                if relationship.metadata.get("origin") != "AssumptionLedgerAgent"
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
