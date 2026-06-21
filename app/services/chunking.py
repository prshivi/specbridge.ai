import re
from collections import Counter
from uuid import UUID

from app.models.document import (
    BlockType,
    ChunkStatistics,
    ChunkType,
    DocumentBlock,
    DocumentChunk,
    NormalizedDocument,
)

REQUIREMENT_PATTERN = re.compile(
    r"(?im)^(?:[-*]\s*)?(?:REQ[-\s]?\d+|requirement\b|the system\b|the platform\b|"
    r"the application\b|users?\b).*(?:\bmust\b|\bshall\b|\bshould\b|\bmay\b)|"
    r"\b(?:must|shall|required to)\b"
)
BUSINESS_RULE_PATTERN = re.compile(r"(?i)\b(?:business\s+rule|BR[-\s]?\d+|rule:)\b")
ACCEPTANCE_PATTERN = re.compile(
    r"(?i)\b(?:acceptance\s+criteria|given\b.*\bwhen\b.*\bthen\b|scenario:|expected result)\b"
)
WORKFLOW_PATTERN = re.compile(
    r"(?i)\b(?:workflow|process flow|user flow|step\s+\d+|first,|next,|then,|finally,)\b"
)


class SemanticChunker:
    """Create structural chunks using deterministic document semantics."""

    def chunk(
        self,
        document_id: UUID,
        document: NormalizedDocument,
    ) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        pending: list[DocumentBlock] = []
        current_heading: str | None = None
        current_section: str | None = None
        current_level = 1

        def append_chunk(
            text: str,
            chunk_type: ChunkType,
            block: DocumentBlock | None = None,
        ) -> None:
            value = text.strip()
            if not value:
                return
            number = len(chunks) + 1
            page = block.page if block else self._first_page(pending)
            heading = (block.heading if block else None) or current_heading
            section = (block.section if block else None) or current_section
            chunks.append(
                DocumentChunk(
                    id=f"{document_id}:{number}",
                    document_id=document_id,
                    text=value,
                    page=page,
                    heading=heading,
                    section=section,
                    chunk_type=chunk_type,
                    chunk_number=number,
                )
            )

        def flush_pending() -> None:
            if not pending:
                return
            body = "\n\n".join(block.text for block in pending)
            text = f"{current_heading}\n\n{body}" if current_heading else body
            chunk_type = (
                ChunkType.SUBHEADING if current_level > 1 else ChunkType.HEADING
            )
            append_chunk(text, chunk_type)
            pending.clear()

        for block in document.blocks:
            if block.block_type is BlockType.HEADING:
                flush_pending()
                current_heading = block.heading or block.text
                current_section = block.section or current_section
                current_level = block.heading_level or 1
                continue

            if block.block_type is BlockType.TABLE:
                flush_pending()
                append_chunk(block.text, ChunkType.TABLE, block)
                continue

            chunk_type = self._classify(block.text, current_heading)
            if chunk_type is None:
                pending.append(block)
            else:
                flush_pending()
                append_chunk(block.text, chunk_type, block)

        flush_pending()
        if not chunks and current_heading:
            append_chunk(current_heading, ChunkType.HEADING)
        return chunks

    def statistics(
        self,
        document_id: UUID,
        chunks: list[DocumentChunk],
    ) -> ChunkStatistics:
        counts = Counter(chunk.chunk_type for chunk in chunks)
        return ChunkStatistics(
            document_id=document_id,
            total_chunks=len(chunks),
            total_characters=sum(len(chunk.text) for chunk in chunks),
            pages=sorted({chunk.page for chunk in chunks if chunk.page is not None}),
            chunks_by_type={
                chunk_type: counts.get(chunk_type, 0) for chunk_type in ChunkType
            },
        )

    @staticmethod
    def _classify(text: str, heading: str | None) -> ChunkType | None:
        context = f"{heading or ''}\n{text}"
        if ACCEPTANCE_PATTERN.search(context):
            return ChunkType.ACCEPTANCE_CRITERIA
        if BUSINESS_RULE_PATTERN.search(context):
            return ChunkType.BUSINESS_RULE
        if WORKFLOW_PATTERN.search(context):
            return ChunkType.WORKFLOW
        if REQUIREMENT_PATTERN.search(context):
            return ChunkType.REQUIREMENT
        return None

    @staticmethod
    def _first_page(blocks: list[DocumentBlock]) -> int | None:
        return next((block.page for block in blocks if block.page is not None), None)

