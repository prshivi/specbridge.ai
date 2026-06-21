from __future__ import annotations

import hashlib
import json
from datetime import UTC
from uuid import UUID

from app.agents.business_to_engineering import (
    BusinessToEngineeringProvider,
    BusinessToEngineeringTranslationAgent,
    OpenAIBusinessToEngineeringProvider,
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
    DocumentChunksNotFoundError,
    EngineeringBlueprintNotFoundError,
    EngineeringTranslationError,
    EngineeringTranslationNotConfiguredError,
    KnowledgeGraphNotFoundError,
)
from app.models.ambiguity import AmbiguityDetectionResult
from app.models.assumption_ledger import FrameworkAssumptionLedgerResult
from app.models.conflict_detection import ConflictDetectionAgentResult
from app.models.document import DocumentChunk
from app.models.engineering_blueprint import (
    BlueprintArtifact,
    BusinessToEngineeringOutput,
    EngineeringArtifactType,
    EngineeringBlueprintResult,
)
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
from app.services.chunks import ChunkService
from app.services.conflict_detection import FrameworkConflictDetectionService
from app.services.engineering_blueprint_store import EngineeringBlueprintStore
from app.services.framework_assumptions import FrameworkAssumptionLedgerService
from app.services.knowledge import KnowledgeGraphService
from app.services.knowledge_store import KnowledgeGraphStore
from app.services.missing_requirement_detection import (
    MissingRequirementDetectionService,
)
from app.services.requirement_extraction import RequirementExtractionService
from app.services.specification_dna import SpecificationDNAService


class BusinessToEngineeringTranslationService:
    """Generate, store, and graph-link framework Engineering Blueprints."""

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
        assumption_service: FrameworkAssumptionLedgerService | None = None,
        knowledge_service: KnowledgeGraphService | None = None,
        knowledge_store: KnowledgeGraphStore | None = None,
        store: EngineeringBlueprintStore | None = None,
        provider: BusinessToEngineeringProvider | None = None,
        engine: AgentPipelineEngine | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_translator_model
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
        self._assumption_service = assumption_service or (
            FrameworkAssumptionLedgerService(settings)
        )
        self._knowledge_service = knowledge_service or KnowledgeGraphService(settings)
        self._knowledge_store = knowledge_store or KnowledgeGraphStore(
            settings.understanding_cache_db
        )
        self._store = store or EngineeringBlueprintStore(
            settings.agent_framework_db
        )
        self._provider = provider
        self._agent = BusinessToEngineeringTranslationAgent(provider=provider)
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
    ) -> EngineeringBlueprintResult:
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
        assumptions = self._assumption_service.list(document_id)
        graph = self._get_or_build_graph(document_id)
        fingerprint = self._source_fingerprint(
            chunks,
            dna.source_fingerprint,
            requirements,
            ambiguities,
            conflicts,
            missing,
            assumptions,
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
                "ambiguity_detection": self._result(
                    "ambiguity_detection",
                    ambiguities.model_dump(mode="json"),
                ),
                "conflict_detection": self._result(
                    "conflict_detection",
                    {
                        "conflicts": [
                            item.model_dump(mode="json")
                            for item in conflicts.conflicts
                        ]
                    },
                ),
                "missing_requirement_detection": self._result(
                    "missing_requirement_detection",
                    {
                        "missing_requirements": [
                            item.model_dump(mode="json")
                            for item in missing.missing_requirements
                        ]
                    },
                ),
                "assumption_ledger": self._result(
                    "assumption_ledger",
                    assumptions.model_dump(mode="json"),
                ),
            },
        )
        try:
            agent_result = self._engine.execute_agent(self._agent.name, context)
            output = BusinessToEngineeringOutput.model_validate(
                agent_result.output
            )
            graph_updated = self._update_graph(
                document_id,
                output,
                graph,
            )
        except EngineeringTranslationError:
            raise
        except Exception as error:
            raise EngineeringTranslationError(
                "The BusinessToEngineeringTranslationAgent model call failed."
            ) from error

        artifacts = [
            artifact
            for blueprint in output.requirement_blueprints
            for artifact in blueprint.artifacts
        ]
        result = EngineeringBlueprintResult(
            document_id=document_id,
            requirement_blueprints=output.requirement_blueprints,
            total_requirements=len(output.requirement_blueprints),
            total_artifacts=len(artifacts),
            clarification_artifacts=sum(
                artifact.artifact_type is EngineeringArtifactType.OPEN_QUESTION
                for artifact in artifacts
            ),
            cached=agent_result.cached,
            model=self._model,
            agent_version=self._agent.version,
            source_fingerprint=fingerprint,
            execution_time_ms=agent_result.execution_time_ms,
            generated_at=agent_result.completed_at.astimezone(UTC),
            knowledge_graph_updated=graph_updated,
        )
        self._store.replace(result)
        return result

    def list(self, document_id: UUID) -> EngineeringBlueprintResult:
        result = self._store.get_result(document_id)
        if result is None:
            raise EngineeringBlueprintNotFoundError(
                "An Engineering Blueprint has not been generated for this document."
            )
        return result

    def get(self, document_id: UUID, artifact_id: str) -> BlueprintArtifact:
        artifact = self._store.get(document_id, artifact_id)
        if artifact is None:
            raise EngineeringBlueprintNotFoundError(
                f"Engineering artifact '{artifact_id}' was not found for this "
                "document."
            )
        return artifact

    def _get_or_build_graph(self, document_id: UUID) -> KnowledgeModel:
        try:
            return self._knowledge_service.get(document_id)
        except KnowledgeGraphNotFoundError:
            self._knowledge_service.build(document_id)
            return self._knowledge_service.get(document_id)

    def _create_provider(self) -> BusinessToEngineeringProvider:
        api_key = (
            self._settings.openai_api_key.get_secret_value()
            if self._settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise EngineeringTranslationNotConfiguredError(
                "OPENAI_API_KEY is required to run "
                "BusinessToEngineeringTranslationAgent."
            )
        return OpenAIBusinessToEngineeringProvider(
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
        output: BusinessToEngineeringOutput,
        graph: KnowledgeModel,
    ) -> bool:
        entities: list[KnowledgeEntity] = []
        relationships: list[KnowledgeRelationship] = []
        indexes = {
            EntityType.REQUIREMENT: self._index(
                graph, EntityType.REQUIREMENT, "requirement_id"
            ),
            EntityType.ASSUMPTION: self._index(
                graph, EntityType.ASSUMPTION, "assumption_id"
            ),
            EntityType.AMBIGUITY_ISSUE: self._index(
                graph, EntityType.AMBIGUITY_ISSUE, "ambiguity_id"
            ),
            EntityType.CONFLICT_ISSUE: self._index(
                graph, EntityType.CONFLICT_ISSUE, "conflict_id"
            ),
            EntityType.MISSING_REQUIREMENT_ISSUE: self._index(
                graph,
                EntityType.MISSING_REQUIREMENT_ISSUE,
                "missing_requirement_id",
            ),
        }
        for blueprint in output.requirement_blueprints:
            for artifact in blueprint.artifacts:
                node_id = (
                    f"kg:{document_id}:engineering_artifact:"
                    f"{artifact.artifact_id.casefold()}"
                )
                entities.append(
                    KnowledgeEntity(
                        id=node_id,
                        document_id=document_id,
                        entity_type=EntityType.ENGINEERING_ARTIFACT,
                        title=artifact.title,
                        description=artifact.description,
                        source_chunk_ids=artifact.source_chunk_ids,
                        confidence=artifact.confidence,
                        metadata={
                            "artifact_id": artifact.artifact_id,
                            "requirement_id": artifact.requirement_id,
                            "artifact_type": artifact.artifact_type.value,
                            "provenance": artifact.provenance.value,
                            "traceability_score": artifact.traceability_score,
                            "payload": artifact.payload.model_dump(mode="json"),
                            "origin": (
                                "BusinessToEngineeringTranslationAgent"
                            ),
                        },
                    )
                )
                targets: list[KnowledgeEntity] = []
                references = (
                    (
                        EntityType.REQUIREMENT,
                        [artifact.requirement_id],
                    ),
                    (
                        EntityType.ASSUMPTION,
                        artifact.related_assumption_ids,
                    ),
                    (
                        EntityType.AMBIGUITY_ISSUE,
                        artifact.related_ambiguity_ids,
                    ),
                    (
                        EntityType.CONFLICT_ISSUE,
                        artifact.related_conflict_ids,
                    ),
                    (
                        EntityType.MISSING_REQUIREMENT_ISSUE,
                        artifact.related_missing_requirement_ids,
                    ),
                )
                for entity_type, identifiers in references:
                    targets.extend(
                        indexes[entity_type][identifier]
                        for identifier in identifiers
                        if identifier in indexes[entity_type]
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
                                        *artifact.source_chunk_ids,
                                        *target.source_chunk_ids,
                                    ]
                                )
                            ),
                            confidence=artifact.confidence,
                            metadata={
                                "origin": (
                                    "BusinessToEngineeringTranslationAgent"
                                )
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
        assumptions: FrameworkAssumptionLedgerResult,
        graph: KnowledgeModel,
    ) -> str:
        payload = {
            "dna_fingerprint": dna_fingerprint,
            "requirements": requirements.model_dump(mode="json"),
            "ambiguities": ambiguities.model_dump(mode="json"),
            "conflicts": conflicts.model_dump(mode="json"),
            "missing": missing.model_dump(mode="json"),
            "assumptions": assumptions.model_dump(mode="json"),
            "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            "graph_entities": [
                entity.model_dump(mode="json")
                for entity in graph.entities
                if entity.entity_type is not EntityType.ENGINEERING_ARTIFACT
            ],
            "graph_relationships": [
                relationship.model_dump(mode="json")
                for relationship in graph.relationships
                if relationship.metadata.get("origin")
                != "BusinessToEngineeringTranslationAgent"
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
