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
from app.agents.requirement_extraction import (
    OpenAIRequirementExtractionProvider,
    RequirementExtractionAgent,
    RequirementExtractionProvider,
)
from app.core.config import Settings
from app.core.exceptions import (
    DocumentChunksNotFoundError,
    ExtractedRequirementsNotFoundError,
    KnowledgeGraphNotFoundError,
    RequirementExtractionError,
    RequirementExtractionNotConfiguredError,
)
from app.models.document import DocumentChunk
from app.models.knowledge import (
    EntityType,
    KnowledgeEntity,
    KnowledgeModel,
    KnowledgeRelationship,
    RelationshipType,
)
from app.models.requirement_extraction import (
    ExtractedRequirement,
    RequirementExtraction,
    RequirementExtractionResult,
)
from app.models.specification_dna import SpecificationDNAResult
from app.services.chunks import ChunkService
from app.services.knowledge import KnowledgeGraphService
from app.services.knowledge_store import KnowledgeGraphStore
from app.services.requirement_extraction_store import RequirementExtractionStore
from app.services.specification_dna import SpecificationDNAService


class RequirementExtractionService:
    """Execute, store, retrieve, and graph-link framework requirements."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        dna_service: SpecificationDNAService | None = None,
        knowledge_service: KnowledgeGraphService | None = None,
        knowledge_store: KnowledgeGraphStore | None = None,
        store: RequirementExtractionStore | None = None,
        provider: RequirementExtractionProvider | None = None,
        engine: AgentPipelineEngine | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_requirements_model
        self._chunk_service = chunk_service or ChunkService(settings)
        self._dna_service = dna_service or SpecificationDNAService(settings)
        self._knowledge_service = knowledge_service or KnowledgeGraphService(settings)
        self._knowledge_store = knowledge_store or KnowledgeGraphStore(
            settings.understanding_cache_db
        )
        self._store = store or RequirementExtractionStore(
            settings.agent_framework_db
        )
        self._provider = provider
        self._agent = RequirementExtractionAgent(provider=provider)
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
    ) -> RequirementExtractionResult:
        chunks = self._chunk_service.get_chunks(document_id)
        if not chunks:
            raise DocumentChunksNotFoundError(
                "No parsed chunks were found for this document."
            )
        dna_result = self._dna_service.get(document_id)
        knowledge_graph = self._get_or_build_knowledge_graph(document_id)
        fingerprint = self._source_fingerprint(
            chunks,
            dna_result,
            knowledge_graph,
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
        dependency_result = AgentResult(
            agent_name="specification_understanding",
            output=dna_result.specification_dna.model_dump(mode="json"),
            confidence=1.0,
            source_chunks=list(
                dict.fromkeys(
                    chunk_id
                    for item in self._dna_evidence_items(dna_result)
                    for chunk_id in item.source_chunk_ids
                )
            ),
            cached=dna_result.cached,
        )
        context = AgentContext(
            knowledge_graph=knowledge_graph,
            specification_dna=dna_result.specification_dna,
            chunks=chunks,
            configuration={
                "source_fingerprint": fingerprint,
                "force_refresh": force_refresh,
                "model": self._model,
            },
            llm_provider=provider,
            results={"specification_understanding": dependency_result},
        )
        try:
            agent_result = self._engine.execute_agent(self._agent.name, context)
            extraction = RequirementExtraction.model_validate(agent_result.output)
            graph_updated = self._update_knowledge_graph(
                document_id,
                extraction.requirements,
                knowledge_graph,
            )
        except RequirementExtractionError:
            raise
        except Exception as error:
            raise RequirementExtractionError(
                "The requirement extraction model call failed."
            ) from error

        result = RequirementExtractionResult(
            document_id=document_id,
            requirements=extraction.requirements,
            cached=agent_result.cached,
            model=self._model,
            agent_version=self._agent.version,
            source_fingerprint=fingerprint,
            execution_time_ms=agent_result.execution_time_ms,
            extracted_at=agent_result.completed_at.astimezone(UTC),
            knowledge_graph_updated=graph_updated,
        )
        self._store.replace(result)
        return result

    def list(self, document_id: UUID) -> RequirementExtractionResult:
        result = self._store.get_result(document_id)
        if result is None:
            raise ExtractedRequirementsNotFoundError(
                "Requirements have not been extracted for this document."
            )
        return result

    def get(
        self,
        document_id: UUID,
        requirement_id: str,
    ) -> ExtractedRequirement:
        requirement = self._store.get(document_id, requirement_id)
        if requirement is None:
            raise ExtractedRequirementsNotFoundError(
                f"Requirement '{requirement_id}' was not found for this document."
            )
        return requirement

    def _get_or_build_knowledge_graph(self, document_id: UUID) -> KnowledgeModel:
        try:
            return self._knowledge_service.get(document_id)
        except KnowledgeGraphNotFoundError:
            self._knowledge_service.build(document_id)
            return self._knowledge_service.get(document_id)

    def _create_provider(self) -> RequirementExtractionProvider:
        api_key = (
            self._settings.openai_api_key.get_secret_value()
            if self._settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise RequirementExtractionNotConfiguredError(
                "OPENAI_API_KEY is required to run RequirementExtractionAgent."
            )
        return OpenAIRequirementExtractionProvider(
            api_key=api_key,
            model=self._model,
        )

    def _update_knowledge_graph(
        self,
        document_id: UUID,
        requirements: list[ExtractedRequirement],
        graph: KnowledgeModel,
    ) -> bool:
        entities: list[KnowledgeEntity] = []
        relationships: list[KnowledgeRelationship] = []
        candidates = [
            entity
            for entity in graph.entities
            if entity.entity_type
            in {
                EntityType.SECTION,
                EntityType.ACTOR,
                EntityType.WORKFLOW,
                EntityType.INTEGRATION,
                EntityType.BUSINESS_RULE,
            }
        ]
        for requirement in requirements:
            entity_id = (
                f"kg:{document_id}:requirement:"
                f"{requirement.requirement_id.casefold()}"
            )
            entity = KnowledgeEntity(
                id=entity_id,
                document_id=document_id,
                entity_type=EntityType.REQUIREMENT,
                title=requirement.title,
                description=requirement.description,
                source_chunk_ids=requirement.source_chunk_ids,
                confidence=requirement.confidence,
                metadata={
                    "requirement_id": requirement.requirement_id,
                    "category": requirement.category.value,
                    "priority": requirement.priority.value,
                    "source_section": requirement.source_section,
                    "explicit_or_inferred": requirement.explicit_or_inferred.value,
                    "ambiguity_flag": requirement.ambiguity_flag,
                    "missing_info_flag": requirement.missing_info_flag,
                    "origin": "RequirementExtractionAgent",
                },
            )
            entities.append(entity)
            for target in candidates:
                relationship_type = self._relationship_type(
                    requirement,
                    target,
                )
                if relationship_type is None:
                    continue
                evidence_overlap = bool(
                    set(requirement.source_chunk_ids)
                    & set(target.source_chunk_ids)
                )
                title_mentioned = (
                    len(target.title) >= 3
                    and target.title.casefold()
                    in (
                        requirement.description
                        + " "
                        + requirement.evidence_text
                    ).casefold()
                )
                same_section = (
                    target.metadata.get("section_number")
                    == requirement.source_section
                    or target.metadata.get("section")
                    == requirement.source_section
                )
                if not (evidence_overlap or title_mentioned or same_section):
                    continue
                source_id, target_id = entity.id, target.id
                if relationship_type is RelationshipType.CONTAINS:
                    source_id, target_id = target.id, entity.id
                relationships.append(
                    KnowledgeRelationship(
                        id=self._relationship_id(
                            source_id,
                            relationship_type,
                            target_id,
                        ),
                        document_id=document_id,
                        source_id=source_id,
                        target_id=target_id,
                        relationship_type=relationship_type,
                        source_chunk_ids=list(
                            dict.fromkeys(
                                [
                                    *requirement.source_chunk_ids,
                                    *target.source_chunk_ids,
                                ]
                            )
                        ),
                        confidence=(
                            0.95 if evidence_overlap or title_mentioned else 0.75
                        ),
                        metadata={
                            "basis": (
                                "shared_evidence"
                                if evidence_overlap
                                else "text_reference"
                                if title_mentioned
                                else "same_section"
                            ),
                            "origin": "RequirementExtractionAgent",
                        },
                    )
                )
        self._knowledge_store.upsert(
            document_id=document_id,
            entities=entities,
            relationships=relationships,
        )
        return True

    @staticmethod
    def _relationship_type(
        requirement: ExtractedRequirement,
        target: KnowledgeEntity,
    ) -> RelationshipType | None:
        mapping = {
            EntityType.SECTION: RelationshipType.BELONGS_TO,
            EntityType.ACTOR: RelationshipType.PERFORMED_BY,
            EntityType.WORKFLOW: RelationshipType.CONTAINS,
            EntityType.INTEGRATION: RelationshipType.INTEGRATES_WITH,
            EntityType.BUSINESS_RULE: RelationshipType.REFERENCES,
        }
        return mapping.get(target.entity_type)

    @staticmethod
    def _relationship_id(
        source_id: str,
        relationship_type: RelationshipType,
        target_id: str,
    ) -> str:
        value = f"{source_id}|{relationship_type.value}|{target_id}"
        return f"kgr:{hashlib.sha1(value.encode()).hexdigest()[:16]}"

    @staticmethod
    def _source_fingerprint(
        chunks: list[DocumentChunk],
        dna_result: SpecificationDNAResult,
        graph: KnowledgeModel,
    ) -> str:
        base_entities = [
            entity.model_dump(mode="json")
            for entity in graph.entities
            if entity.metadata.get("origin") != "RequirementExtractionAgent"
        ]
        base_relationships = [
            relationship.model_dump(mode="json")
            for relationship in graph.relationships
            if relationship.metadata.get("origin") != "RequirementExtractionAgent"
        ]
        payload = {
            "dna_source_fingerprint": dna_result.source_fingerprint,
            "dna": dna_result.specification_dna.model_dump(mode="json"),
            "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            "knowledge_graph": {
                "entities": base_entities,
                "relationships": base_relationships,
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _dna_evidence_items(dna_result: SpecificationDNAResult) -> list[object]:
        dna = dna_result.specification_dna
        items: list[object] = []
        if dna.project_name:
            items.append(dna.project_name)
        if dna.project_summary:
            items.append(dna.project_summary)
        for field in (
            "business_objectives",
            "actors",
            "user_personas",
            "modules",
            "workflows",
            "integrations",
            "business_rules",
            "constraints",
            "explicit_assumptions",
            "glossary",
            "key_terminology",
        ):
            items.extend(getattr(dna, field))
        return items
