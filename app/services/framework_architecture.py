from __future__ import annotations

import hashlib
import json
from datetime import UTC
from uuid import UUID

from app.agents.architecture_recommendation import (
    ArchitectureBlueprintProvider,
    ArchitectureRecommendationAgent,
    OpenAIArchitectureBlueprintProvider,
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
    ArchitectureBlueprintNotFoundError,
    ArchitectureRecommendationError,
    ArchitectureRecommendationNotConfiguredError,
    DocumentChunksNotFoundError,
    KnowledgeGraphNotFoundError,
)
from app.models.architecture_blueprint import (
    ArchitectureBlueprint,
    ArchitectureBlueprintResult,
    ArchitectureDiagramCollection,
    ArchitectureProvenance,
)
from app.models.assumption_ledger import FrameworkAssumptionLedgerResult
from app.models.document import DocumentChunk
from app.models.engineering_blueprint import EngineeringBlueprintResult
from app.models.knowledge import (
    EntityType,
    KnowledgeEntity,
    KnowledgeModel,
    KnowledgeRelationship,
    RelationshipType,
)
from app.models.requirement_extraction import RequirementExtractionResult
from app.services.architecture_blueprint_store import ArchitectureBlueprintStore
from app.services.business_to_engineering import (
    BusinessToEngineeringTranslationService,
)
from app.services.chunks import ChunkService
from app.services.framework_assumptions import FrameworkAssumptionLedgerService
from app.services.knowledge import KnowledgeGraphService
from app.services.knowledge_store import KnowledgeGraphStore
from app.services.requirement_extraction import RequirementExtractionService
from app.services.specification_dna import SpecificationDNAService


class FrameworkArchitectureRecommendationService:
    """Generate, persist, and graph-link the Architecture Blueprint."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        dna_service: SpecificationDNAService | None = None,
        requirement_service: RequirementExtractionService | None = None,
        assumption_service: FrameworkAssumptionLedgerService | None = None,
        engineering_service: BusinessToEngineeringTranslationService | None = None,
        knowledge_service: KnowledgeGraphService | None = None,
        knowledge_store: KnowledgeGraphStore | None = None,
        store: ArchitectureBlueprintStore | None = None,
        provider: ArchitectureBlueprintProvider | None = None,
        engine: AgentPipelineEngine | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_architecture_model
        self._chunk_service = chunk_service or ChunkService(settings)
        self._dna_service = dna_service or SpecificationDNAService(settings)
        self._requirement_service = requirement_service or (
            RequirementExtractionService(settings)
        )
        self._assumption_service = assumption_service or (
            FrameworkAssumptionLedgerService(settings)
        )
        self._engineering_service = engineering_service or (
            BusinessToEngineeringTranslationService(settings)
        )
        self._knowledge_service = knowledge_service or KnowledgeGraphService(settings)
        self._knowledge_store = knowledge_store or KnowledgeGraphStore(
            settings.understanding_cache_db
        )
        self._store = store or ArchitectureBlueprintStore(
            settings.agent_framework_db
        )
        self._provider = provider
        self._agent = ArchitectureRecommendationAgent(provider=provider)
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
    ) -> ArchitectureBlueprintResult:
        chunks = self._chunk_service.get_chunks(document_id)
        if not chunks:
            raise DocumentChunksNotFoundError(
                "No parsed chunks were found for this document."
            )
        dna = self._dna_service.get(document_id)
        requirements = self._requirement_service.list(document_id)
        assumptions = self._assumption_service.list(document_id)
        engineering = self._engineering_service.list(document_id)
        graph = self._get_or_build_graph(document_id)
        fingerprint = self._source_fingerprint(
            chunks,
            dna.source_fingerprint,
            requirements,
            assumptions,
            engineering,
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
                "requirement_extraction": self._result(
                    "requirement_extraction",
                    {
                        "requirements": [
                            item.model_dump(mode="json")
                            for item in requirements.requirements
                        ]
                    },
                ),
                "assumption_ledger": self._result(
                    "assumption_ledger",
                    assumptions.model_dump(mode="json"),
                ),
                "business_to_engineering_translation": self._result(
                    "business_to_engineering_translation",
                    engineering.model_dump(mode="json"),
                ),
            },
        )
        try:
            agent_result = self._engine.execute_agent(self._agent.name, context)
            architecture = ArchitectureBlueprint.model_validate(agent_result.output)
            graph_updated = self._update_graph(
                document_id,
                architecture,
                graph,
            )
        except ArchitectureRecommendationError:
            raise
        except Exception as error:
            raise ArchitectureRecommendationError(
                "The ArchitectureRecommendationAgent model call failed."
            ) from error

        result = ArchitectureBlueprintResult(
            document_id=document_id,
            architecture=architecture,
            total_recommendations=len(architecture.recommendations),
            total_diagrams=len(architecture.diagrams),
            clarification_recommendations=sum(
                item.provenance is ArchitectureProvenance.NEEDS_CLARIFICATION
                for item in architecture.recommendations
            ),
            cached=agent_result.cached,
            model=self._model,
            agent_version=self._agent.version,
            source_fingerprint=fingerprint,
            execution_time_ms=agent_result.execution_time_ms,
            generated_at=agent_result.completed_at.astimezone(UTC),
            knowledge_graph_updated=graph_updated,
        )
        self._store.set(result)
        return result

    def get(self, document_id: UUID) -> ArchitectureBlueprintResult:
        result = self._store.get(document_id)
        if result is None:
            raise ArchitectureBlueprintNotFoundError(
                "An Architecture Blueprint has not been generated for this document."
            )
        return result

    def diagrams(self, document_id: UUID) -> ArchitectureDiagramCollection:
        diagrams = self._store.diagrams(document_id)
        if diagrams is None:
            raise ArchitectureBlueprintNotFoundError(
                "An Architecture Blueprint has not been generated for this document."
            )
        return diagrams

    def _get_or_build_graph(self, document_id: UUID) -> KnowledgeModel:
        try:
            return self._knowledge_service.get(document_id)
        except KnowledgeGraphNotFoundError:
            self._knowledge_service.build(document_id)
            return self._knowledge_service.get(document_id)

    def _create_provider(self) -> ArchitectureBlueprintProvider:
        api_key = (
            self._settings.openai_api_key.get_secret_value()
            if self._settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise ArchitectureRecommendationNotConfiguredError(
                "OPENAI_API_KEY is required to run ArchitectureRecommendationAgent."
            )
        return OpenAIArchitectureBlueprintProvider(
            api_key=api_key,
            model=self._model,
        )

    @staticmethod
    def _result(name: str, output: object) -> AgentResult:
        return AgentResult(
            agent_name=name,
            output=output,
            confidence=1.0,
            cached=True,
        )

    def _update_graph(
        self,
        document_id: UUID,
        architecture: ArchitectureBlueprint,
        graph: KnowledgeModel,
    ) -> bool:
        entities: list[KnowledgeEntity] = []
        relationships: list[KnowledgeRelationship] = []
        indexes = {
            EntityType.REQUIREMENT: self._index(
                graph, EntityType.REQUIREMENT, "requirement_id"
            ),
            EntityType.ENGINEERING_ARTIFACT: self._index(
                graph, EntityType.ENGINEERING_ARTIFACT, "artifact_id"
            ),
            EntityType.ASSUMPTION: self._index(
                graph, EntityType.ASSUMPTION, "assumption_id"
            ),
        }
        items = [
            *architecture.recommendations,
            *architecture.diagrams,
        ]
        for item in items:
            identifier = (
                item.recommendation_id
                if hasattr(item, "recommendation_id")
                else item.diagram_id
            )
            node_id = f"kg:{document_id}:architecture_node:{identifier.casefold()}"
            entities.append(
                KnowledgeEntity(
                    id=node_id,
                    document_id=document_id,
                    entity_type=EntityType.ARCHITECTURE_NODE,
                    title=item.title,
                    description=getattr(item, "recommendation", item.reason),
                    source_chunk_ids=item.source_chunk_ids,
                    confidence=item.confidence,
                    metadata={
                        "architecture_id": identifier,
                        "node_kind": (
                            "recommendation"
                            if hasattr(item, "recommendation_id")
                            else "diagram"
                        ),
                        "type": (
                            item.recommendation_type.value
                            if hasattr(item, "recommendation_type")
                            else item.diagram_type.value
                        ),
                        "provenance": item.provenance.value,
                        "traceability_score": item.traceability_score,
                        "origin": "ArchitectureRecommendationAgent",
                    },
                )
            )
            targets: list[KnowledgeEntity] = []
            references = (
                (EntityType.REQUIREMENT, item.related_requirement_ids),
                (EntityType.ENGINEERING_ARTIFACT, item.related_artifact_ids),
                (EntityType.ASSUMPTION, item.related_assumption_ids),
            )
            for entity_type, identifiers in references:
                targets.extend(
                    indexes[entity_type][target_id]
                    for target_id in identifiers
                    if target_id in indexes[entity_type]
                )
            for target in {target.id: target for target in targets}.values():
                relationships.append(
                    KnowledgeRelationship(
                        id=self._relationship_id(node_id, target.id),
                        document_id=document_id,
                        source_id=node_id,
                        target_id=target.id,
                        relationship_type=RelationshipType.ARCHITECTURE_EDGE,
                        source_chunk_ids=list(
                            dict.fromkeys(
                                [*item.source_chunk_ids, *target.source_chunk_ids]
                            )
                        ),
                        confidence=item.confidence,
                        metadata={"origin": "ArchitectureRecommendationAgent"},
                    )
                )
        self._knowledge_store.upsert(
            document_id=document_id,
            entities=entities,
            relationships=relationships,
        )
        return True

    @staticmethod
    def _index(
        graph: KnowledgeModel,
        entity_type: EntityType,
        metadata_key: str,
    ) -> dict[str, KnowledgeEntity]:
        result: dict[str, KnowledgeEntity] = {}
        for entity in graph.entities:
            if entity.entity_type is not entity_type:
                continue
            result[entity.id] = entity
            if entity.metadata.get(metadata_key):
                result[str(entity.metadata[metadata_key])] = entity
        return result

    @staticmethod
    def _relationship_id(source_id: str, target_id: str) -> str:
        value = f"{source_id}|architecture_edge|{target_id}"
        return f"kgr:{hashlib.sha1(value.encode()).hexdigest()[:16]}"

    @staticmethod
    def _source_fingerprint(
        chunks: list[DocumentChunk],
        dna_fingerprint: str,
        requirements: RequirementExtractionResult,
        assumptions: FrameworkAssumptionLedgerResult,
        engineering: EngineeringBlueprintResult,
        graph: KnowledgeModel,
    ) -> str:
        payload = {
            "dna_fingerprint": dna_fingerprint,
            "requirements": requirements.model_dump(mode="json"),
            "assumptions": assumptions.model_dump(mode="json"),
            "engineering": engineering.model_dump(mode="json"),
            "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            "graph_entities": [
                item.model_dump(mode="json")
                for item in graph.entities
                if item.entity_type is not EntityType.ARCHITECTURE_NODE
            ],
            "graph_relationships": [
                item.model_dump(mode="json")
                for item in graph.relationships
                if item.metadata.get("origin") != "ArchitectureRecommendationAgent"
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
