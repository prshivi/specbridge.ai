import hashlib
import math
from pathlib import Path
from typing import Any
from uuid import UUID

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.models.document import ChunkType, DocumentChunk

VECTOR_DIMENSIONS = 32


def deterministic_vector(text: str) -> list[float]:
    """Create a stable local vector without a model or network call."""
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=VECTOR_DIMENSIONS).digest()
    values = [(byte - 127.5) / 127.5 for byte in digest]
    magnitude = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / magnitude for value in values]


class ChromaChunkStore:
    """Persist and retrieve semantic chunks from local ChromaDB."""

    def __init__(
        self,
        path: Path,
        collection_name: str,
        client: Any | None = None,
    ) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self._client = client or chromadb.PersistentClient(
            path=str(path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=None,
            metadata={
                "description": "SpecBridge deterministic semantic chunks",
                "embedding_mode": "local_hash_no_model",
            },
        )

    def replace_document_chunks(
        self,
        document_id: UUID,
        chunks: list[DocumentChunk],
    ) -> None:
        document_key = str(document_id)
        self._collection.delete(where={"document_id": document_key})
        if not chunks:
            return
        self._collection.add(
            ids=[chunk.id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=[deterministic_vector(chunk.text) for chunk in chunks],
            metadatas=[self._metadata(chunk) for chunk in chunks],
        )

    def get_document_chunks(self, document_id: UUID) -> list[DocumentChunk]:
        result = self._collection.get(
            where={"document_id": str(document_id)},
            include=["documents", "metadatas"],
        )
        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        chunks = [
            self._to_chunk(chunk_id, text, metadata)
            for chunk_id, text, metadata in zip(ids, documents, metadatas, strict=True)
        ]
        return sorted(chunks, key=lambda chunk: chunk.chunk_number)

    @staticmethod
    def _metadata(chunk: DocumentChunk) -> dict[str, str | int]:
        return {
            "document_id": str(chunk.document_id),
            "page": chunk.page or 0,
            "heading": chunk.heading or "",
            "section": chunk.section or "",
            "chunk_type": chunk.chunk_type.value,
            "chunk_number": chunk.chunk_number,
        }

    @staticmethod
    def _to_chunk(
        chunk_id: str,
        text: str,
        metadata: dict[str, Any],
    ) -> DocumentChunk:
        page = int(metadata.get("page", 0))
        return DocumentChunk(
            id=chunk_id,
            document_id=UUID(str(metadata["document_id"])),
            text=text,
            page=page or None,
            heading=str(metadata.get("heading", "")) or None,
            section=str(metadata.get("section", "")) or None,
            chunk_type=ChunkType(str(metadata["chunk_type"])),
            chunk_number=int(metadata["chunk_number"]),
        )
