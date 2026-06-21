from uuid import uuid4

from app.models.document import BlockType, ChunkType, DocumentBlock, NormalizedDocument
from app.services.chunking import SemanticChunker


def test_semantic_chunker_uses_structure_and_business_semantics() -> None:
    document_id = uuid4()
    document = NormalizedDocument(
        text="structured requirements",
        blocks=[
            DocumentBlock(
                block_type=BlockType.HEADING,
                text="Account Registration",
                heading="Account Registration",
                section="1",
                heading_level=1,
                page=1,
            ),
            DocumentBlock(
                block_type=BlockType.PARAGRAPH,
                text="This capability creates a customer account.",
                heading="Account Registration",
                section="1",
                page=1,
            ),
            DocumentBlock(
                block_type=BlockType.HEADING,
                text="Implementation Notes",
                heading="Implementation Notes",
                section="1.0",
                heading_level=2,
                page=1,
            ),
            DocumentBlock(
                block_type=BlockType.PARAGRAPH,
                text="Registration is available on web and mobile channels.",
                heading="Implementation Notes",
                section="1.0",
                page=1,
            ),
            DocumentBlock(
                block_type=BlockType.HEADING,
                text="Requirements",
                heading="Requirements",
                section="1.1",
                heading_level=2,
                page=1,
            ),
            DocumentBlock(
                block_type=BlockType.PARAGRAPH,
                text="REQ-001: The platform must validate the email address.",
                heading="Requirements",
                section="1.1",
                page=1,
            ),
            DocumentBlock(
                block_type=BlockType.PARAGRAPH,
                text="BR-001: A verified email may belong to one account.",
                heading="Business Rules",
                section="1.2",
                page=2,
            ),
            DocumentBlock(
                block_type=BlockType.PARAGRAPH,
                text="Given a customer, when they register, then an account is created.",
                heading="Acceptance Criteria",
                section="1.3",
                page=2,
            ),
            DocumentBlock(
                block_type=BlockType.PARAGRAPH,
                text="Workflow: Step 1 validate. Step 2 create the account.",
                heading="Workflow",
                section="1.4",
                page=2,
            ),
            DocumentBlock(
                block_type=BlockType.TABLE,
                text="Field\tRule\nEmail\tRequired",
                heading="Validation Matrix",
                section="1.5",
                page=3,
            ),
        ],
    )

    chunks = SemanticChunker().chunk(document_id, document)

    assert [chunk.chunk_number for chunk in chunks] == list(range(1, len(chunks) + 1))
    assert {chunk.chunk_type for chunk in chunks} == {
        ChunkType.HEADING,
        ChunkType.SUBHEADING,
        ChunkType.REQUIREMENT,
        ChunkType.BUSINESS_RULE,
        ChunkType.ACCEPTANCE_CRITERIA,
        ChunkType.WORKFLOW,
        ChunkType.TABLE,
    }
    requirement = next(
        chunk for chunk in chunks if chunk.chunk_type is ChunkType.REQUIREMENT
    )
    assert requirement.document_id == document_id
    assert requirement.page == 1
    assert requirement.heading == "Requirements"
    assert requirement.section == "1.1"


def test_chunk_statistics_include_type_counts_and_pages() -> None:
    document_id = uuid4()
    document = NormalizedDocument(
        text="Requirement",
        blocks=[
            DocumentBlock(
                block_type=BlockType.PARAGRAPH,
                text="The platform must store the document.",
                page=4,
            )
        ],
    )
    chunker = SemanticChunker()
    chunks = chunker.chunk(document_id, document)

    statistics = chunker.statistics(document_id, chunks)

    assert statistics.total_chunks == 1
    assert statistics.pages == [4]
    assert statistics.chunks_by_type[ChunkType.REQUIREMENT] == 1
