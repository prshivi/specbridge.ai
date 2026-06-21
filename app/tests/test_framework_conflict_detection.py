from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.agents.conflict_detection import ConflictDetectionAgent
from app.agents.framework import AgentContext, AgentPipelineEngine, AgentRegistry, AgentResult
from app.core.config import Settings
from app.models.conflict_detection import (
    ConflictDetectionOutput,
    DetectedConflict,
    DetectedConflictSeverity,
    DetectedConflictType,
    RecommendedStakeholder,
)
from app.models.document import ChunkType, DocumentChunk
from app.models.knowledge import EntityType, KnowledgeEntity, KnowledgeModel
from app.models.requirement_extraction import (
    EvidenceOrigin,
    ExtractedRequirement,
    ExtractedRequirementCategory,
    ExtractedRequirementPriority,
    RequirementExtractionResult,
)
from app.models.specification_dna import SpecificationDNAResult
from app.services.conflict_detection import FrameworkConflictDetectionService
from app.services.conflict_detection_store import FrameworkConflictStore
from app.services.knowledge_store import KnowledgeGraphStore
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


class StubKnowledgeService:
    def __init__(self, model: KnowledgeModel) -> None:
        self.model = model

    def get(self, document_id: UUID) -> KnowledgeModel:
        assert document_id == self.model.document_id
        return self.model


class StubConflictProvider:
    def __init__(self, output: ConflictDetectionOutput) -> None:
        self.output = output
        self.calls = 0
        self.context = ""

    def detect(self, context: str) -> ConflictDetectionOutput:
        self.calls += 1
        self.context = context
        return self.output


def build_framework_conflict_chunks(document_id: UUID) -> list[DocumentChunk]:
    return [
        DocumentChunk(
            id=f"{document_id}:1",
            document_id=document_id,
            text="Customers may request a refund within 7 days.",
            page=1,
            heading="Refund Policy",
            section="2.1",
            chunk_type=ChunkType.BUSINESS_RULE,
            chunk_number=1,
        ),
        DocumentChunk(
            id=f"{document_id}:2",
            document_id=document_id,
            text="Refunds are not allowed.",
            page=2,
            heading="Refund Policy",
            section="2.2",
            chunk_type=ChunkType.BUSINESS_RULE,
            chunk_number=2,
        ),
    ]


def build_framework_requirements(
    document_id: UUID,
) -> RequirementExtractionResult:
    return RequirementExtractionResult(
        document_id=document_id,
        requirements=[
            ExtractedRequirement(
                requirement_id="BR-001",
                title="Refund window",
                description="Customers may request a refund within 7 days.",
                category=ExtractedRequirementCategory.BUSINESS_RULE,
                priority=ExtractedRequirementPriority.UNSPECIFIED,
                confidence=0.99,
                source_chunk_ids=[f"{document_id}:1"],
                source_section="2.1",
                evidence_text="Customers may request a refund within 7 days.",
                explicit_or_inferred=EvidenceOrigin.EXPLICIT,
                ambiguity_flag=False,
                missing_info_flag=False,
            ),
            ExtractedRequirement(
                requirement_id="BR-002",
                title="No refunds",
                description="Refunds are not allowed.",
                category=ExtractedRequirementCategory.BUSINESS_RULE,
                priority=ExtractedRequirementPriority.UNSPECIFIED,
                confidence=0.99,
                source_chunk_ids=[f"{document_id}:2"],
                source_section="2.2",
                evidence_text="Refunds are not allowed.",
                explicit_or_inferred=EvidenceOrigin.EXPLICIT,
                ambiguity_flag=False,
                missing_info_flag=False,
            ),
        ],
        cached=True,
        model="requirements-model",
        agent_version="1",
        source_fingerprint="requirements-v1",
        execution_time_ms=0,
        extracted_at=datetime.now(UTC),
        knowledge_graph_updated=True,
    )


def build_framework_conflict_output(document_id: UUID) -> ConflictDetectionOutput:
    return ConflictDetectionOutput(
        conflicts=[
            DetectedConflict(
                conflict_id="CON-001",
                title="Contradictory refund policy",
                conflict_type=DetectedConflictType.BUSINESS_RULE_VS_BUSINESS_RULE,
                description=(
                    "One rule permits refunds during a seven-day window while "
                    "another prohibits all refunds."
                ),
                severity=DetectedConflictSeverity.CRITICAL,
                confidence=0.99,
                involved_requirement_ids=[],
                involved_business_rule_ids=["BR-001", "BR-002"],
                evidence_texts=[
                    "Customers may request a refund within 7 days.",
                    "Refunds are not allowed.",
                ],
                source_chunk_ids=[
                    f"{document_id}:1",
                    f"{document_id}:2",
                ],
                source_sections=["2.1", "2.2"],
                why_it_matters=(
                    "The implementation cannot enforce both refund outcomes."
                ),
                recommended_resolution_question=(
                    "Are refunds prohibited entirely, or allowed within seven days?"
                ),
                recommended_stakeholder=RecommendedStakeholder.PRODUCT,
                blocking_for_development=True,
            )
        ]
    )


def build_framework_conflict_graph(document_id: UUID) -> KnowledgeModel:
    entities = []
    for requirement in build_framework_requirements(document_id).requirements:
        entities.append(
            KnowledgeEntity(
                id=(
                    f"kg:{document_id}:requirement:"
                    f"{requirement.requirement_id.casefold()}"
                ),
                document_id=document_id,
                entity_type=EntityType.REQUIREMENT,
                title=requirement.title,
                description=requirement.description,
                source_chunk_ids=requirement.source_chunk_ids,
                confidence=requirement.confidence,
                metadata={
                    "requirement_id": requirement.requirement_id,
                    "origin": "RequirementExtractionAgent",
                },
            )
        )
        entities.append(
            KnowledgeEntity(
                id=f"rule:{requirement.requirement_id}",
                document_id=document_id,
                entity_type=EntityType.BUSINESS_RULE,
                title=requirement.requirement_id,
                description=requirement.description,
                source_chunk_ids=requirement.source_chunk_ids,
                confidence=requirement.confidence,
                metadata={"explicit_id": requirement.requirement_id},
            )
        )
    return KnowledgeModel(
        document_id=document_id,
        entities=entities,
        relationships=[],
        built_at=datetime.now(UTC),
    )


def build_framework_conflict_service(
    tmp_path: Path,
    document_id: UUID,
    provider: StubConflictProvider,
) -> FrameworkConflictDetectionService:
    settings = Settings(
        agent_framework_db=tmp_path / "agents.db",
        understanding_cache_db=tmp_path / "knowledge.db",
        openai_conflict_model="test-conflict-model",
        agent_retry_attempts=1,
        _env_file=None,
    )
    graph = build_framework_conflict_graph(document_id)
    graph_store = KnowledgeGraphStore(settings.understanding_cache_db)
    graph_store.replace(graph)
    return FrameworkConflictDetectionService(
        settings,
        chunk_service=StubChunkService(
            build_framework_conflict_chunks(document_id)
        ),
        dna_service=StubDNAService(document_id),
        requirement_service=StubRequirementService(
            build_framework_requirements(document_id)
        ),
        knowledge_service=StubKnowledgeService(graph),
        knowledge_store=graph_store,
        store=FrameworkConflictStore(settings.agent_framework_db),
        provider=provider,
    )


def framework_context(
    document_id: UUID,
    provider: StubConflictProvider,
) -> AgentContext:
    requirements = build_framework_requirements(document_id)
    return AgentContext(
        specification_dna=build_specification_dna(document_id),
        knowledge_graph=build_framework_conflict_graph(document_id),
        chunks=build_framework_conflict_chunks(document_id),
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
            )
        },
    )


def test_conflict_agent_executes_with_requirement_dependency() -> None:
    document_id = uuid4()
    provider = StubConflictProvider(
        build_framework_conflict_output(document_id)
    )
    agent = ConflictDetectionAgent(provider)
    registry = AgentRegistry()
    registry.register(agent)

    result = AgentPipelineEngine(registry).execute_agent(
        agent.name,
        framework_context(document_id, provider),
    )

    assert result.output["conflicts"][0]["conflict_id"] == "CON-001"
    assert result.source_chunks == [
        f"{document_id}:1",
        f"{document_id}:2",
    ]
    assert "TOTAL_REQUIREMENTS: 2" in provider.context


def test_conflict_schema_requires_resolution_question() -> None:
    document_id = uuid4()
    with pytest.raises(ValueError, match="must end with"):
        build_framework_conflict_output(document_id).conflicts[0].model_copy(
            update={"recommended_resolution_question": "Choose the policy"}
        ).model_validate(
            {
                **build_framework_conflict_output(document_id)
                .conflicts[0]
                .model_dump(),
                "recommended_resolution_question": "Choose the policy",
            }
        )


def test_conflict_agent_rejects_untraceable_evidence() -> None:
    document_id = uuid4()
    output = build_framework_conflict_output(document_id)
    output.conflicts[0].evidence_texts[0] = "Refunds require manager approval."
    provider = StubConflictProvider(output)

    with pytest.raises(ValueError, match="evidence was not found"):
        ConflictDetectionAgent(provider).execute(
            framework_context(document_id, provider)
        )


def test_no_supported_conflict_returns_empty_output() -> None:
    document_id = uuid4()
    provider = StubConflictProvider(ConflictDetectionOutput(conflicts=[]))
    result = ConflictDetectionAgent(provider).execute(
        framework_context(document_id, provider)
    )

    assert result.output["conflicts"] == []
    assert result.source_chunks == []


def test_service_persists_caches_and_retrieves_conflicts(tmp_path: Path) -> None:
    document_id = uuid4()
    provider = StubConflictProvider(
        build_framework_conflict_output(document_id)
    )
    service = build_framework_conflict_service(
        tmp_path,
        document_id,
        provider,
    )

    first = service.run(document_id)
    second = service.run(document_id)
    one = service.get(document_id, "CON-001")

    assert first.cached is False
    assert second.cached is True
    assert provider.calls == 1
    assert one.blocking_for_development is True
    assert one.recommended_resolution_question.endswith("?")


def test_service_adds_conflict_issue_and_links_to_graph(tmp_path: Path) -> None:
    document_id = uuid4()
    service = build_framework_conflict_service(
        tmp_path,
        document_id,
        StubConflictProvider(build_framework_conflict_output(document_id)),
    )

    service.run(document_id)
    graph = service._knowledge_store.get(document_id)

    conflict_nodes = [
        entity
        for entity in graph.entities
        if entity.entity_type is EntityType.CONFLICT_ISSUE
    ]
    assert len(conflict_nodes) == 1
    involved = [
        relationship
        for relationship in graph.relationships
        if relationship.relationship_type.value == "involves"
    ]
    assert len(involved) == 4
