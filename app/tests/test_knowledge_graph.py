from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import Settings
from app.models.document import ChunkType, DocumentChunk
from app.models.knowledge import EntityType, RelationshipType
from app.services.knowledge import KnowledgeGraphService
from app.services.knowledge_store import KnowledgeGraphStore


class StubKnowledgeChunkService:
    def __init__(self, chunks: list[DocumentChunk]) -> None:
        self._chunks = chunks

    def get_chunks(self, document_id: UUID) -> list[DocumentChunk]:
        return [
            chunk for chunk in self._chunks if chunk.document_id == document_id
        ]


def build_knowledge_chunks(document_id: UUID) -> list[DocumentChunk]:
    values = [
        (
            ChunkType.REQUIREMENT,
            "REQ-001: As a customer, the platform must validate the Account record. "
            "Data Entity: Account. Integration: Stripe. "
            "Only an administrator may approve it. "
            "POST /accounts",
            "Account Requirements",
            "1.1",
        ),
        (
            ChunkType.BUSINESS_RULE,
            "BR-001: An account must not have more than one active owner.",
            "Account Requirements",
            "1.1",
        ),
        (
            ChunkType.REQUIREMENT,
            "REQ-002 depends on REQ-001 and references BR-001. "
            "The platform shall send an email notification.",
            "Account Requirements",
            "1.1",
        ),
        (
            ChunkType.ACCEPTANCE_CRITERIA,
            "Given a valid customer, when registration is submitted, "
            "then the account is created.",
            "Account Requirements",
            "1.1",
        ),
        (
            ChunkType.WORKFLOW,
            "Workflow: Step 1 execute REQ-001. Step 2 execute REQ-002.",
            "Account Requirements",
            "1.1",
        ),
        (
            ChunkType.HEADING,
            "Glossary\nCustomer: A person registering an account.",
            "Glossary",
            "2",
        ),
    ]
    return [
        DocumentChunk(
            id=f"{document_id}:{index}",
            document_id=document_id,
            text=text,
            page=1 if index < 6 else 2,
            heading=heading,
            section=section,
            chunk_type=chunk_type,
            chunk_number=index,
        )
        for index, (chunk_type, text, heading, section) in enumerate(values, start=1)
    ]


def build_knowledge_service(
    tmp_path: Path,
    document_id: UUID,
) -> KnowledgeGraphService:
    settings = Settings(
        understanding_cache_db=tmp_path / "knowledge.db",
        _env_file=None,
    )
    return KnowledgeGraphService(
        settings,
        chunk_service=StubKnowledgeChunkService(
            build_knowledge_chunks(document_id)
        ),
        store=KnowledgeGraphStore(settings.understanding_cache_db),
    )


def test_builds_and_persists_deterministic_knowledge_graph(tmp_path: Path) -> None:
    document_id = uuid4()
    service = build_knowledge_service(tmp_path, document_id)

    result = service.build(document_id)
    model = service.get(document_id)

    assert result.entity_count == len(model.entities)
    assert result.entities_by_type[EntityType.DOCUMENT] == 1
    assert result.entities_by_type[EntityType.REQUIREMENT] == 2
    assert result.entities_by_type[EntityType.BUSINESS_RULE] == 1
    assert result.entities_by_type[EntityType.WORKFLOW] == 1
    assert result.entities_by_type[EntityType.ACTOR] >= 1
    assert result.entities_by_type[EntityType.INTEGRATION] == 1
    assert result.entities_by_type[EntityType.DATA_ENTITY] == 1
    assert result.entities_by_type[EntityType.API_REFERENCE] == 1
    assert result.entities_by_type[EntityType.GLOSSARY_TERM] == 1
    assert all(entity.source_chunk_ids for entity in model.entities)
    assert all(0 <= entity.confidence <= 1 for entity in model.entities)


def test_creates_required_relationship_types_from_explicit_evidence(
    tmp_path: Path,
) -> None:
    document_id = uuid4()
    service = build_knowledge_service(tmp_path, document_id)
    service.build(document_id)
    model = service.get(document_id)
    relationship_types = {
        relationship.relationship_type for relationship in model.relationships
    }

    assert RelationshipType.BELONGS_TO in relationship_types
    assert RelationshipType.DEPENDS_ON in relationship_types
    assert RelationshipType.REFERENCES in relationship_types
    assert RelationshipType.CONTAINS in relationship_types
    assert RelationshipType.INTEGRATES_WITH in relationship_types
    assert RelationshipType.USES in relationship_types
    assert RelationshipType.VALIDATED_BY in relationship_types
    assert RelationshipType.REQUIRES in relationship_types


def test_networkx_graph_json_matches_persisted_model(tmp_path: Path) -> None:
    document_id = uuid4()
    service = build_knowledge_service(tmp_path, document_id)
    service.build(document_id)
    model = service.get(document_id)

    graph = service.get_graph(document_id)

    assert graph.directed is True
    assert graph.multigraph is True
    assert graph.node_count == len(model.entities)
    assert graph.edge_count == len(model.relationships)
    assert {node.id for node in graph.nodes} == {
        entity.id for entity in model.entities
    }


def test_rebuild_replaces_previous_graph_without_duplicates(tmp_path: Path) -> None:
    document_id = uuid4()
    service = build_knowledge_service(tmp_path, document_id)

    first = service.build(document_id)
    second = service.build(document_id)

    assert second.entity_count == first.entity_count
    assert second.relationship_count == first.relationship_count
    assert len(service.get(document_id).entities) == first.entity_count
