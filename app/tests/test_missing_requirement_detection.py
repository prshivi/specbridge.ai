from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.agents.framework import AgentContext, AgentPipelineEngine, AgentRegistry, AgentResult
from app.agents.missing_requirement_detection import MissingRequirementDetectionAgent
from app.core.config import Settings
from app.models.conflict_detection import (
    ConflictDetectionAgentResult,
    ConflictDetectionOutput,
    RecommendedStakeholder,
)
from app.models.document import ChunkType, DocumentChunk
from app.models.knowledge import EntityType, KnowledgeEntity, KnowledgeModel
from app.models.missing_requirements import (
    GapEvidenceOrigin,
    MissingRequirementDetectionOutput,
    MissingRequirementGapType,
    MissingRequirementIssue,
    MissingRequirementSeverity,
)
from app.models.requirement_extraction import (
    EvidenceOrigin,
    ExtractedRequirement,
    ExtractedRequirementCategory,
    ExtractedRequirementPriority,
    RequirementExtractionResult,
)
from app.models.specification_dna import SpecificationDNAResult
from app.services.knowledge_store import KnowledgeGraphStore
from app.services.missing_requirement_detection import (
    MissingRequirementDetectionService,
)
from app.services.missing_requirement_store import MissingRequirementStore
from app.tests.test_specification_dna_agent import build_specification_dna


class StubChunkService:
    def __init__(self, chunks: list[DocumentChunk]) -> None:
        self.chunks = chunks

    def get_chunks(self, document_id: UUID) -> list[DocumentChunk]:
        assert all(chunk.document_id == document_id for chunk in self.chunks)
        return self.chunks


class StubDNAService:
    def __init__(self, document_id: UUID) -> None:
        self.result = SpecificationDNAResult(
            document_id=document_id,
            specification_dna=build_specification_dna(document_id),
            cached=True,
            model="dna-model",
            agent_version="2",
            source_fingerprint="dna-v1",
            execution_time_ms=0,
            generated_at=datetime.now(UTC),
        )

    def get(self, document_id: UUID) -> SpecificationDNAResult:
        assert document_id == self.result.document_id
        return self.result


class StubRequirementService:
    def __init__(self, result: RequirementExtractionResult) -> None:
        self.result = result

    def list(self, document_id: UUID) -> RequirementExtractionResult:
        assert document_id == self.result.document_id
        return self.result


class StubConflictService:
    def __init__(self, result: ConflictDetectionAgentResult) -> None:
        self.result = result

    def list(self, document_id: UUID) -> ConflictDetectionAgentResult:
        assert document_id == self.result.document_id
        return self.result


class StubKnowledgeService:
    def __init__(self, model: KnowledgeModel) -> None:
        self.model = model

    def get(self, document_id: UUID) -> KnowledgeModel:
        assert document_id == self.model.document_id
        return self.model


class StubMissingProvider:
    def __init__(self, output: MissingRequirementDetectionOutput) -> None:
        self.output = output
        self.calls = 0
        self.context = ""

    def detect(self, context: str) -> MissingRequirementDetectionOutput:
        self.calls += 1
        self.context = context
        return self.output


def build_missing_chunks(document_id: UUID) -> list[DocumentChunk]:
    return [
        DocumentChunk(
            id=f"{document_id}:1",
            document_id=document_id,
            text=(
                "INT-001: The registration workflow sends validated account "
                "details to Email Provider."
            ),
            page=1,
            heading="Registration Integration",
            section="3.1",
            chunk_type=ChunkType.WORKFLOW,
            chunk_number=1,
        )
    ]


def build_missing_requirements(
    document_id: UUID,
) -> RequirementExtractionResult:
    return RequirementExtractionResult(
        document_id=document_id,
        requirements=[
            ExtractedRequirement(
                requirement_id="INT-001",
                title="Send account details",
                description=(
                    "The registration workflow sends validated account details "
                    "to Email Provider."
                ),
                category=ExtractedRequirementCategory.INTEGRATION,
                priority=ExtractedRequirementPriority.UNSPECIFIED,
                confidence=0.96,
                source_chunk_ids=[f"{document_id}:1"],
                source_section="3.1",
                evidence_text=(
                    "The registration workflow sends validated account details "
                    "to Email Provider."
                ),
                explicit_or_inferred=EvidenceOrigin.EXPLICIT,
                ambiguity_flag=False,
                missing_info_flag=True,
            )
        ],
        cached=True,
        model="requirements-model",
        agent_version="1",
        source_fingerprint="requirements-v1",
        execution_time_ms=0,
        extracted_at=datetime.now(UTC),
        knowledge_graph_updated=True,
    )


def build_empty_conflicts(document_id: UUID) -> ConflictDetectionAgentResult:
    return ConflictDetectionAgentResult(
        document_id=document_id,
        conflicts=[],
        cached=True,
        model="conflict-model",
        agent_version="1",
        source_fingerprint="conflicts-v1",
        execution_time_ms=0,
        analyzed_at=datetime.now(UTC),
        knowledge_graph_updated=True,
    )


def graph_entity(
    document_id: UUID,
    entity_type: EntityType,
    entity_id: str,
    title: str,
    chunk_id: str,
) -> KnowledgeEntity:
    return KnowledgeEntity(
        id=entity_id,
        document_id=document_id,
        entity_type=entity_type,
        title=title,
        description=title,
        source_chunk_ids=[chunk_id],
        confidence=1.0,
        metadata={},
    )


def build_missing_graph(document_id: UUID) -> KnowledgeModel:
    chunk_id = f"{document_id}:1"
    return KnowledgeModel(
        document_id=document_id,
        entities=[
            KnowledgeEntity(
                id=f"kg:{document_id}:requirement:int-001",
                document_id=document_id,
                entity_type=EntityType.REQUIREMENT,
                title="Send account details",
                description="Send account details to Email Provider.",
                source_chunk_ids=[chunk_id],
                confidence=0.96,
                metadata={
                    "requirement_id": "INT-001",
                    "origin": "RequirementExtractionAgent",
                },
            ),
            graph_entity(
                document_id,
                EntityType.WORKFLOW,
                "workflow:registration",
                "Registration workflow",
                chunk_id,
            ),
            graph_entity(
                document_id,
                EntityType.ACTOR,
                "actor:customer",
                "Customer",
                chunk_id,
            ),
            graph_entity(
                document_id,
                EntityType.INTEGRATION,
                "integration:email-provider",
                "Email Provider",
                chunk_id,
            ),
        ],
        relationships=[],
        built_at=datetime.now(UTC),
    )


def build_missing_output(document_id: UUID) -> MissingRequirementDetectionOutput:
    return MissingRequirementDetectionOutput(
        missing_requirements=[
            MissingRequirementIssue(
                missing_requirement_id="MISS-001",
                title="Potentially missing integration failure handling",
                gap_type=MissingRequirementGapType.INTEGRATION_FAILURE_HANDLING,
                description=(
                    "The integration behavior is defined, but the specification "
                    "does not state what happens when Email Provider is unavailable."
                ),
                severity=MissingRequirementSeverity.HIGH,
                confidence=0.82,
                related_requirement_ids=["INT-001"],
                related_workflow_ids=["workflow:registration"],
                related_actor_ids=["actor:customer"],
                source_chunk_ids=[f"{document_id}:1"],
                source_sections=["3.1"],
                why_it_matters=(
                    "An undefined failure path can leave registration incomplete "
                    "or produce inconsistent user outcomes."
                ),
                suggested_requirement_text=(
                    "The system shall define failure, retry, and user-feedback "
                    "behavior when Email Provider is unavailable."
                ),
                clarification_question=(
                    "What should happen when Email Provider is unavailable or "
                    "returns an error?"
                ),
                recommended_stakeholder=RecommendedStakeholder.PRODUCT,
                blocking_for_development=True,
                explicit_gap_or_inferred_gap=GapEvidenceOrigin.INFERRED_GAP,
            )
        ]
    )


def missing_context(
    document_id: UUID,
    provider: StubMissingProvider,
) -> AgentContext:
    requirements = build_missing_requirements(document_id)
    conflicts = build_empty_conflicts(document_id)
    return AgentContext(
        specification_dna=build_specification_dna(document_id),
        knowledge_graph=build_missing_graph(document_id),
        chunks=build_missing_chunks(document_id),
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
            ),
        },
    )


def build_missing_service(
    tmp_path: Path,
    document_id: UUID,
    provider: StubMissingProvider,
) -> MissingRequirementDetectionService:
    settings = Settings(
        agent_framework_db=tmp_path / "agents.db",
        understanding_cache_db=tmp_path / "knowledge.db",
        openai_missing_requirements_model="test-missing-model",
        agent_retry_attempts=1,
        _env_file=None,
    )
    graph = build_missing_graph(document_id)
    graph_store = KnowledgeGraphStore(settings.understanding_cache_db)
    graph_store.replace(graph)
    return MissingRequirementDetectionService(
        settings,
        chunk_service=StubChunkService(build_missing_chunks(document_id)),
        dna_service=StubDNAService(document_id),
        requirement_service=StubRequirementService(
            build_missing_requirements(document_id)
        ),
        conflict_service=StubConflictService(build_empty_conflicts(document_id)),
        knowledge_service=StubKnowledgeService(graph),
        knowledge_store=graph_store,
        store=MissingRequirementStore(settings.agent_framework_db),
        provider=provider,
    )


def test_agent_executes_contextual_gap_detection() -> None:
    document_id = uuid4()
    provider = StubMissingProvider(build_missing_output(document_id))
    agent = MissingRequirementDetectionAgent(provider)
    registry = AgentRegistry()
    registry.register(agent)

    result = AgentPipelineEngine(registry).execute_agent(
        agent.name,
        missing_context(document_id, provider),
    )

    issue = result.output["missing_requirements"][0]
    assert issue["gap_type"] == "integration_failure_handling"
    assert issue["explicit_gap_or_inferred_gap"] == "inferred_gap"
    assert "FLAGGED_REQUIREMENT_GAPS" in provider.context


def test_schema_requires_contextual_anchor_and_question() -> None:
    with pytest.raises(ValueError, match="contextual traceability"):
        MissingRequirementIssue(
            missing_requirement_id="MISS-001",
            title="Generic gap",
            gap_type=MissingRequirementGapType.MONITORING_OBSERVABILITY,
            description="Monitoring is not described.",
            severity=MissingRequirementSeverity.LOW,
            confidence=0.3,
            why_it_matters="Operational issues could be harder to diagnose.",
            suggested_requirement_text="Define monitoring expectations.",
            clarification_question="Is monitoring required?",
            recommended_stakeholder=RecommendedStakeholder.DEVOPS,
            blocking_for_development=False,
            explicit_gap_or_inferred_gap=GapEvidenceOrigin.INFERRED_GAP,
        )

    issue = build_missing_output(uuid4()).missing_requirements[0].model_dump()
    issue["clarification_question"] = "Define the failure behavior"
    with pytest.raises(ValueError, match="must end with"):
        MissingRequirementIssue.model_validate(issue)


def test_agent_rejects_unknown_source_traceability() -> None:
    document_id = uuid4()
    output = build_missing_output(document_id)
    output.missing_requirements[0].source_chunk_ids = ["unknown:1"]
    provider = StubMissingProvider(output)

    with pytest.raises(ValueError, match="unknown source chunks"):
        MissingRequirementDetectionAgent(provider).execute(
            missing_context(document_id, provider)
        )


def test_empty_output_proves_no_forced_checklist_behavior() -> None:
    document_id = uuid4()
    provider = StubMissingProvider(
        MissingRequirementDetectionOutput(missing_requirements=[])
    )

    result = MissingRequirementDetectionAgent(provider).execute(
        missing_context(document_id, provider)
    )

    assert result.output["missing_requirements"] == []
    assert result.source_chunks == []


def test_service_persists_caches_and_retrieves_issues(tmp_path: Path) -> None:
    document_id = uuid4()
    provider = StubMissingProvider(build_missing_output(document_id))
    service = build_missing_service(tmp_path, document_id, provider)

    first = service.run(document_id)
    second = service.run(document_id)
    one = service.get(document_id, "MISS-001")

    assert first.cached is False
    assert second.cached is True
    assert provider.calls == 1
    assert one.clarification_question.endswith("?")
    assert service.list(document_id).missing_requirements == first.missing_requirements


def test_service_adds_issue_and_related_entity_links(tmp_path: Path) -> None:
    document_id = uuid4()
    service = build_missing_service(
        tmp_path,
        document_id,
        StubMissingProvider(build_missing_output(document_id)),
    )

    service.run(document_id)
    graph = service._knowledge_store.get(document_id)

    nodes = [
        entity
        for entity in graph.entities
        if entity.entity_type is EntityType.MISSING_REQUIREMENT_ISSUE
    ]
    assert len(nodes) == 1
    related = [
        relationship
        for relationship in graph.relationships
        if relationship.relationship_type.value == "related_to"
    ]
    assert len(related) == 4
