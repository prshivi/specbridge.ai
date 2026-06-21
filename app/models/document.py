from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentType(StrEnum):
    """Supported document formats."""

    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MARKDOWN = "md"
    XLSX = "xlsx"
    CSV = "csv"


class BlockType(StrEnum):
    """Structural block types emitted by document parsers."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"


class DocumentBlock(BaseModel):
    """One hierarchy-aware block extracted from a source document."""

    block_type: BlockType
    text: str
    page: int | None = Field(default=None, ge=1)
    heading: str | None = None
    section: str | None = None
    heading_level: int | None = Field(default=None, ge=1, le=6)


class NormalizedDocument(BaseModel):
    """Parser-neutral representation used by downstream intelligence services."""

    text: str
    blocks: list[DocumentBlock]


class ParsedDocument(BaseModel):
    """A stored document and its normalized extracted text."""

    id: UUID
    original_filename: str
    storage_key: str
    document_type: DocumentType
    content_type: str
    size_bytes: int = Field(ge=1)
    character_count: int = Field(ge=0)
    extracted_text: str
    uploaded_at: datetime
    chunk_statistics: "ChunkStatistics | None" = None


class ChunkType(StrEnum):
    """Semantic chunk categories."""

    HEADING = "heading"
    SUBHEADING = "subheading"
    REQUIREMENT = "requirement"
    TABLE = "table"
    BUSINESS_RULE = "business_rule"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    WORKFLOW = "workflow"


class DocumentChunk(BaseModel):
    """A semantic unit stored in the vector database."""

    id: str
    document_id: UUID
    text: str
    page: int | None = Field(default=None, ge=1)
    heading: str | None = None
    section: str | None = None
    chunk_type: ChunkType
    chunk_number: int = Field(ge=1)


class ChunkStatistics(BaseModel):
    """Aggregate chunking results for one document."""

    document_id: UUID
    total_chunks: int = Field(ge=0)
    total_characters: int = Field(ge=0)
    pages: list[int]
    chunks_by_type: dict[ChunkType, int]


class ChunkVisualizationNode(BaseModel):
    """A node in the document-to-chunk visualization graph."""

    id: str
    label: str
    node_type: str
    chunk_type: ChunkType | None = None
    chunk_number: int | None = None
    page: int | None = None
    heading: str | None = None
    section: str | None = None
    character_count: int = Field(ge=0)


class ChunkVisualizationEdge(BaseModel):
    """A directed relationship in the chunk visualization graph."""

    source: str
    target: str
    relationship: str


class ChunkVisualization(BaseModel):
    """Frontend-ready graph representation of document chunks."""

    document_id: UUID
    statistics: ChunkStatistics
    nodes: list[ChunkVisualizationNode]
    edges: list[ChunkVisualizationEdge]
