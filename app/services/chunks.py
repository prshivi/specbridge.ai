from uuid import UUID

from app.core.config import Settings
from app.models.document import (
    ChunkStatistics,
    ChunkVisualization,
    ChunkVisualizationEdge,
    ChunkVisualizationNode,
    DocumentChunk,
)
from app.services.chunking import SemanticChunker
from app.vectorstore import ChromaChunkStore


class ChunkService:
    """Read chunk statistics and visualization data from ChromaDB."""

    def __init__(
        self,
        settings: Settings,
        store: ChromaChunkStore | None = None,
        chunker: SemanticChunker | None = None,
    ) -> None:
        self._store = store or ChromaChunkStore(
            settings.chroma_dir,
            settings.chroma_collection,
        )
        self._chunker = chunker or SemanticChunker()

    def get_chunks(self, document_id: UUID) -> list[DocumentChunk]:
        return self._store.get_document_chunks(document_id)

    def get_statistics(self, document_id: UUID) -> ChunkStatistics:
        return self._chunker.statistics(document_id, self.get_chunks(document_id))

    def get_visualization(self, document_id: UUID) -> ChunkVisualization:
        chunks = self.get_chunks(document_id)
        statistics = self._chunker.statistics(document_id, chunks)
        root_id = f"document:{document_id}"
        nodes = [
            ChunkVisualizationNode(
                id=root_id,
                label=f"Document {document_id}",
                node_type="document",
                character_count=statistics.total_characters,
            )
        ]
        edges: list[ChunkVisualizationEdge] = []
        previous_id: str | None = None
        for chunk in chunks:
            nodes.append(
                ChunkVisualizationNode(
                    id=chunk.id,
                    label=f"{chunk.chunk_number}. {chunk.chunk_type.value.replace('_', ' ').title()}",
                    node_type="chunk",
                    chunk_type=chunk.chunk_type,
                    chunk_number=chunk.chunk_number,
                    page=chunk.page,
                    heading=chunk.heading,
                    section=chunk.section,
                    character_count=len(chunk.text),
                )
            )
            edges.append(
                ChunkVisualizationEdge(
                    source=root_id,
                    target=chunk.id,
                    relationship="contains",
                )
            )
            if previous_id:
                edges.append(
                    ChunkVisualizationEdge(
                        source=previous_id,
                        target=chunk.id,
                        relationship="next",
                    )
                )
            previous_id = chunk.id
        return ChunkVisualization(
            document_id=document_id,
            statistics=statistics,
            nodes=nodes,
            edges=edges,
        )

