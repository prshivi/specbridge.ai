from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.agents.framework import AgentContext, AgentPipelineEngine, AgentRegistry
from app.agents.specification_dna import SpecificationUnderstandingAgent
from app.core.config import Settings
from app.models.document import ChunkType, DocumentChunk
from app.models.knowledge import KnowledgeModel
from app.models.specification_dna import (
    ActorDNA,
    EvidenceText,
    GlossaryDNA,
    IntegrationDNA,
    NamedDNAItem,
    SpecificationDNA,
    UserPersonaDNA,
    WorkflowDNA,
)
from app.services.specification_dna import SpecificationDNAService
from app.services.specification_dna_store import SpecificationDNAStore


class StubChunkService:
    def __init__(self, chunks: list[DocumentChunk]) -> None:
        self.chunks = chunks

    def get_chunks(self, document_id: UUID) -> list[DocumentChunk]:
        assert all(chunk.document_id == document_id for chunk in self.chunks)
        return self.chunks


class StubKnowledgeService:
    def __init__(self, document_id: UUID) -> None:
        self.model = KnowledgeModel(
            document_id=document_id,
            entities=[],
            relationships=[],
            built_at=datetime.now(UTC),
        )

    def get(self, document_id: UUID) -> KnowledgeModel:
        assert document_id == self.model.document_id
        return self.model


class StubDNAProvider:
    def __init__(self, dna: SpecificationDNA) -> None:
        self.dna = dna
        self.calls = 0
        self.context = ""

    def extract(self, context: str) -> SpecificationDNA:
        self.calls += 1
        self.context = context
        return self.dna


def build_dna_chunks(document_id: UUID) -> list[DocumentChunk]:
    return [
        DocumentChunk(
            id=f"{document_id}:1",
            document_id=document_id,
            text=(
                "Project: Account Bridge. The objective is to reduce manual "
                "account creation. Actor: Customer. Persona: Retail customer."
            ),
            page=1,
            heading="Project Overview",
            section="1",
            chunk_type=ChunkType.HEADING,
            chunk_number=1,
        ),
        DocumentChunk(
            id=f"{document_id}:2",
            document_id=document_id,
            text=(
                "Workflow: Registration. The customer submits details and the "
                "system validates email. Integration: Email Provider. "
                "BR-001: One email may have one active account."
            ),
            page=2,
            heading="Registration",
            section="2.1",
            chunk_type=ChunkType.WORKFLOW,
            chunk_number=2,
        ),
        DocumentChunk(
            id=f"{document_id}:3",
            document_id=document_id,
            text=(
                "Assumption: Customers can access their email inbox. "
                "Account: A customer identity stored by the platform."
            ),
            page=3,
            heading="Assumptions and Glossary",
            section="3",
            chunk_type=ChunkType.HEADING,
            chunk_number=3,
        ),
    ]


def evidence(
    value: str,
    document_id: UUID,
    chunk_number: int,
    section: str,
) -> EvidenceText:
    return EvidenceText(
        value=value,
        confidence=0.95,
        source_chunk_ids=[f"{document_id}:{chunk_number}"],
        source_document_sections=[section],
    )


def build_specification_dna(document_id: UUID) -> SpecificationDNA:
    return SpecificationDNA(
        project_name=evidence("Account Bridge", document_id, 1, "1"),
        project_summary=evidence(
            "A customer account registration platform.",
            document_id,
            1,
            "1",
        ),
        business_objectives=[
            evidence("Reduce manual account creation.", document_id, 1, "1")
        ],
        actors=[
            ActorDNA(
                name="Customer",
                description="Submits registration details.",
                actor_type="human",
                confidence=0.98,
                source_chunk_ids=[f"{document_id}:1"],
                source_document_sections=["1"],
            )
        ],
        user_personas=[
            UserPersonaDNA(
                name="Retail customer",
                description="A customer registering for an account.",
                goals=[],
                needs=[],
                confidence=0.9,
                source_chunk_ids=[f"{document_id}:1"],
                source_document_sections=["1"],
            )
        ],
        modules=[
            NamedDNAItem(
                name="Registration",
                description="Validates and creates customer accounts.",
                confidence=0.9,
                source_chunk_ids=[f"{document_id}:2"],
                source_document_sections=["2.1"],
            )
        ],
        workflows=[
            WorkflowDNA(
                name="Registration",
                description="Customer details are submitted and email is validated.",
                actors=["Customer"],
                steps=["Submit details", "Validate email"],
                confidence=0.96,
                source_chunk_ids=[f"{document_id}:2"],
                source_document_sections=["2.1"],
            )
        ],
        integrations=[
            IntegrationDNA(
                name="Email Provider",
                description="Supports email validation.",
                external_system="Email Provider",
                purpose="Validate customer email.",
                confidence=0.94,
                source_chunk_ids=[f"{document_id}:2"],
                source_document_sections=["2.1"],
            )
        ],
        business_rules=[
            evidence(
                "One email may have one active account.",
                document_id,
                2,
                "2.1",
            )
        ],
        constraints=[],
        explicit_assumptions=[
            evidence(
                "Customers can access their email inbox.",
                document_id,
                3,
                "3",
            )
        ],
        glossary=[
            GlossaryDNA(
                term="Account",
                definition="A customer identity stored by the platform.",
                confidence=0.98,
                source_chunk_ids=[f"{document_id}:3"],
                source_document_sections=["3"],
            )
        ],
        key_terminology=[
            GlossaryDNA(
                term="Registration",
                definition="The workflow that creates a customer account.",
                confidence=0.9,
                source_chunk_ids=[f"{document_id}:2"],
                source_document_sections=["2.1"],
            )
        ],
    )


def build_dna_service(
    tmp_path: Path,
    document_id: UUID,
    provider: StubDNAProvider,
) -> SpecificationDNAService:
    settings = Settings(
        agent_framework_db=tmp_path / "dna.db",
        openai_understanding_model="test-dna-model",
        agent_retry_attempts=1,
        _env_file=None,
    )
    return SpecificationDNAService(
        settings,
        chunk_service=StubChunkService(build_dna_chunks(document_id)),
        knowledge_service=StubKnowledgeService(document_id),
        store=SpecificationDNAStore(settings.agent_framework_db),
        provider=provider,
    )


def test_framework_agent_populates_evidence_grounded_dna() -> None:
    document_id = uuid4()
    chunks = build_dna_chunks(document_id)
    provider = StubDNAProvider(build_specification_dna(document_id))
    agent = SpecificationUnderstandingAgent(provider)
    registry = AgentRegistry()
    registry.register(agent)
    context = AgentContext(
        chunks=chunks,
        knowledge_graph=StubKnowledgeService(document_id).model,
        llm_provider=provider,
        configuration={"source_fingerprint": "source-v1"},
    )

    result = AgentPipelineEngine(registry).execute_agent(agent.name, context)

    assert result.output["project_name"]["value"] == "Account Bridge"
    assert result.assumptions == []
    assert set(result.source_chunks) == {chunk.id for chunk in chunks}
    assert context.specification_dna.project_name.value == "Account Bridge"
    assert "SOURCE_CHUNK_ID" in provider.context
    assert "SECTION: 2.1" in provider.context


def test_agent_rejects_unknown_source_chunk() -> None:
    document_id = uuid4()
    dna = build_specification_dna(document_id)
    dna.project_name.source_chunk_ids = ["unknown:1"]
    agent = SpecificationUnderstandingAgent(StubDNAProvider(dna))
    context = AgentContext(
        chunks=build_dna_chunks(document_id),
        llm_provider=StubDNAProvider(dna),
    )

    with pytest.raises(ValueError, match="unknown source chunks"):
        agent.execute(context)


def test_agent_rejects_mismatched_source_section() -> None:
    document_id = uuid4()
    dna = build_specification_dna(document_id)
    dna.project_name.source_document_sections = ["9.9"]
    agent = SpecificationUnderstandingAgent(StubDNAProvider(dna))

    with pytest.raises(ValueError, match="do not match"):
        agent.execute(
            AgentContext(
                chunks=build_dna_chunks(document_id),
                llm_provider=StubDNAProvider(dna),
            )
        )


def test_service_stores_and_reuses_specification_dna(tmp_path: Path) -> None:
    document_id = uuid4()
    provider = StubDNAProvider(build_specification_dna(document_id))
    service = build_dna_service(tmp_path, document_id, provider)

    first = service.get(document_id)
    second = service.get(document_id)

    assert first.cached is False
    assert second.cached is True
    assert first.specification_dna == second.specification_dna
    assert provider.calls == 1
    assert first.agent_version == "2"
    assert len(first.source_fingerprint) == 64


def test_force_refresh_executes_agent_again(tmp_path: Path) -> None:
    document_id = uuid4()
    provider = StubDNAProvider(build_specification_dna(document_id))
    service = build_dna_service(tmp_path, document_id, provider)

    service.get(document_id)
    refreshed = service.get(document_id, force_refresh=True)

    assert refreshed.cached is False
    assert provider.calls == 2


def test_dna_schema_has_no_downstream_outputs() -> None:
    properties = SpecificationDNA.model_json_schema()["properties"]

    assert "apis" not in properties
    assert "user_stories" not in properties
    assert "architecture" not in properties
