from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.agents.framework import AgentContext, AgentPipelineEngine, AgentRegistry, AgentResult
from app.agents.requirement_extraction import RequirementExtractionAgent
from app.core.config import Settings
from app.models.document import ChunkType, DocumentChunk
from app.models.knowledge import (
    EntityType,
    KnowledgeEntity,
    KnowledgeModel,
)
from app.models.requirement_extraction import (
    EvidenceOrigin,
    ExtractedRequirement,
    ExtractedRequirementCategory,
    ExtractedRequirementPriority,
    RequirementExtraction,
)
from app.models.specification_dna import SpecificationDNAResult
from app.services.knowledge_store import KnowledgeGraphStore
from app.services.requirement_extraction import RequirementExtractionService
from app.services.requirement_extraction_store import RequirementExtractionStore
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
            source_fingerprint="dna-source-v1",
            execution_time_ms=0,
            generated_at=datetime.now(UTC),
        )

    def get(self, document_id: UUID) -> SpecificationDNAResult:
        assert document_id == self.result.document_id
        return self.result


class StubKnowledgeService:
    def __init__(self, model: KnowledgeModel) -> None:
        self.model = model

    def get(self, document_id: UUID) -> KnowledgeModel:
        assert document_id == self.model.document_id
        return self.model


class StubRequirementExtractionProvider:
    def __init__(self, extraction: RequirementExtraction) -> None:
        self.extraction = extraction
        self.calls = 0
        self.context = ""

    def extract(self, context: str) -> RequirementExtraction:
        self.calls += 1
        self.context = context
        return self.extraction


def build_extraction_chunks(document_id: UUID) -> list[DocumentChunk]:
    return [
        DocumentChunk(
            id=f"{document_id}:1",
            document_id=document_id,
            text=(
                "FR-001: The platform must validate the customer's email address "
                "before creating an account. Only administrators may deactivate "
                "an account."
            ),
            page=1,
            heading="Account Requirements",
            section="1.1",
            chunk_type=ChunkType.REQUIREMENT,
            chunk_number=1,
        ),
        DocumentChunk(
            id=f"{document_id}:2",
            document_id=document_id,
            text=(
                "The registration workflow sends the validated account to "
                "Email Provider. BR-001: One email may have one active account."
            ),
            page=2,
            heading="Registration Workflow",
            section="1.2",
            chunk_type=ChunkType.WORKFLOW,
            chunk_number=2,
        ),
    ]


def build_extraction(document_id: UUID) -> RequirementExtraction:
    return RequirementExtraction(
        requirements=[
            ExtractedRequirement(
                requirement_id="FR-001",
                title="Validate customer email",
                description=(
                    "The platform must validate the customer's email address "
                    "before account creation."
                ),
                category=ExtractedRequirementCategory.VALIDATION_RULE,
                priority=ExtractedRequirementPriority.UNSPECIFIED,
                confidence=0.98,
                source_chunk_ids=[f"{document_id}:1"],
                source_section="1.1",
                evidence_text=(
                    "The platform must validate the customer's email address "
                    "before creating an account."
                ),
                explicit_or_inferred=EvidenceOrigin.EXPLICIT,
                ambiguity_flag=False,
                missing_info_flag=False,
            ),
            ExtractedRequirement(
                requirement_id="PERM-001",
                title="Restrict account deactivation",
                description="Account deactivation is restricted to administrators.",
                category=ExtractedRequirementCategory.PERMISSION_ACCESS,
                priority=ExtractedRequirementPriority.UNSPECIFIED,
                confidence=0.96,
                source_chunk_ids=[f"{document_id}:1"],
                source_section="1.1",
                evidence_text="Only administrators may deactivate an account.",
                explicit_or_inferred=EvidenceOrigin.EXPLICIT,
                ambiguity_flag=False,
                missing_info_flag=False,
            ),
        ]
    )


def knowledge_entity(
    document_id: UUID,
    entity_type: EntityType,
    entity_id: str,
    title: str,
    chunk_id: str,
    section: str,
) -> KnowledgeEntity:
    metadata_key = "section_number" if entity_type is EntityType.SECTION else "section"
    return KnowledgeEntity(
        id=entity_id,
        document_id=document_id,
        entity_type=entity_type,
        title=title,
        description=title,
        source_chunk_ids=[chunk_id],
        confidence=1.0,
        metadata={metadata_key: section},
    )


def build_knowledge_model(document_id: UUID) -> KnowledgeModel:
    return KnowledgeModel(
        document_id=document_id,
        entities=[
            knowledge_entity(
                document_id,
                EntityType.SECTION,
                "section:1.1",
                "Account Requirements",
                f"{document_id}:1",
                "1.1",
            ),
            knowledge_entity(
                document_id,
                EntityType.ACTOR,
                "actor:administrator",
                "administrator",
                f"{document_id}:1",
                "1.1",
            ),
            knowledge_entity(
                document_id,
                EntityType.WORKFLOW,
                "workflow:registration",
                "Registration Workflow",
                f"{document_id}:2",
                "1.2",
            ),
            knowledge_entity(
                document_id,
                EntityType.INTEGRATION,
                "integration:email-provider",
                "Email Provider",
                f"{document_id}:2",
                "1.2",
            ),
            knowledge_entity(
                document_id,
                EntityType.BUSINESS_RULE,
                "rule:br-001",
                "BR-001",
                f"{document_id}:2",
                "1.2",
            ),
        ],
        relationships=[],
        built_at=datetime.now(UTC),
    )


def build_extraction_service(
    tmp_path: Path,
    document_id: UUID,
    provider: StubRequirementExtractionProvider,
) -> RequirementExtractionService:
    settings = Settings(
        agent_framework_db=tmp_path / "agents.db",
        understanding_cache_db=tmp_path / "knowledge.db",
        openai_requirements_model="test-requirement-model",
        agent_retry_attempts=1,
        _env_file=None,
    )
    graph = build_knowledge_model(document_id)
    graph_store = KnowledgeGraphStore(settings.understanding_cache_db)
    graph_store.replace(graph)
    return RequirementExtractionService(
        settings,
        chunk_service=StubChunkService(build_extraction_chunks(document_id)),
        dna_service=StubDNAService(document_id),
        knowledge_service=StubKnowledgeService(graph),
        knowledge_store=graph_store,
        store=RequirementExtractionStore(settings.agent_framework_db),
        provider=provider,
    )


def test_agent_executes_through_framework_with_dna_dependency() -> None:
    document_id = uuid4()
    provider = StubRequirementExtractionProvider(build_extraction(document_id))
    agent = RequirementExtractionAgent(provider)
    registry = AgentRegistry()
    registry.register(agent)
    context = AgentContext(
        specification_dna=build_specification_dna(document_id),
        chunks=build_extraction_chunks(document_id),
        llm_provider=provider,
        results={
            "specification_understanding": AgentResult(
                agent_name="specification_understanding",
                output={},
                confidence=1.0,
            )
        },
    )

    result = AgentPipelineEngine(registry).execute_agent(agent.name, context)

    assert result.output["requirements"][0]["requirement_id"] == "FR-001"
    assert result.source_chunks == [f"{document_id}:1"]
    assert provider.calls == 1
    assert "SPECIFICATION_DNA:" in provider.context


def test_agent_rejects_hallucinated_evidence() -> None:
    document_id = uuid4()
    extraction = build_extraction(document_id)
    extraction.requirements[0].evidence_text = "The platform predicts the future."
    agent = RequirementExtractionAgent(
        StubRequirementExtractionProvider(extraction)
    )

    with pytest.raises(ValueError, match="evidence_text was not found"):
        agent.execute(
            AgentContext(
                specification_dna=build_specification_dna(document_id),
                chunks=build_extraction_chunks(document_id),
                llm_provider=StubRequirementExtractionProvider(extraction),
            )
        )


def test_empty_supported_output_does_not_invent_requirements() -> None:
    document_id = uuid4()
    provider = StubRequirementExtractionProvider(
        RequirementExtraction(requirements=[])
    )
    agent = RequirementExtractionAgent(provider)

    result = agent.execute(
        AgentContext(
            specification_dna=build_specification_dna(document_id),
            chunks=build_extraction_chunks(document_id),
            llm_provider=provider,
        )
    )

    assert result.output["requirements"] == []
    assert result.source_chunks == []


def test_service_persists_reuses_and_retrieves_requirements(tmp_path: Path) -> None:
    document_id = uuid4()
    provider = StubRequirementExtractionProvider(build_extraction(document_id))
    service = build_extraction_service(tmp_path, document_id, provider)

    first = service.run(document_id)
    second = service.run(document_id)
    one = service.get(document_id, "FR-001")

    assert first.cached is False
    assert second.cached is True
    assert provider.calls == 1
    assert one.source_chunk_ids == [f"{document_id}:1"]
    assert service.list(document_id).requirements == first.requirements


def test_service_updates_knowledge_graph_with_traceable_links(
    tmp_path: Path,
) -> None:
    document_id = uuid4()
    provider = StubRequirementExtractionProvider(build_extraction(document_id))
    service = build_extraction_service(tmp_path, document_id, provider)

    result = service.run(document_id)
    graph = service._knowledge_store.get(document_id)

    assert result.knowledge_graph_updated is True
    requirement_nodes = [
        entity
        for entity in graph.entities
        if entity.entity_type is EntityType.REQUIREMENT
        and entity.metadata.get("origin") == "RequirementExtractionAgent"
    ]
    assert len(requirement_nodes) == 2
    relationship_types = {
        relationship.relationship_type for relationship in graph.relationships
    }
    assert "belongs_to" in relationship_types
    assert "performed_by" in relationship_types


def test_requirement_json_schema_has_all_requested_fields() -> None:
    properties = ExtractedRequirement.model_json_schema()["properties"]

    assert set(properties) == {
        "requirement_id",
        "title",
        "description",
        "category",
        "priority",
        "confidence",
        "source_chunk_ids",
        "source_section",
        "evidence_text",
        "explicit_or_inferred",
        "ambiguity_flag",
        "missing_info_flag",
    }
