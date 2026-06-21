from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.models.document import ChunkStatistics, ChunkVisualization
from app.services.chunks import ChunkService

router = APIRouter(prefix="/documents", tags=["chunks"])


def get_chunk_service() -> ChunkService:
    return ChunkService(get_settings())


@router.get("/{document_id}/chunks/statistics", response_model=ChunkStatistics)
def get_chunk_statistics(document_id: UUID) -> ChunkStatistics:
    """Return semantic chunk counts and page coverage."""
    statistics = get_chunk_service().get_statistics(document_id)
    if statistics.total_chunks == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No chunks were found for this document.",
        )
    return statistics


@router.get("/{document_id}/chunks/visualization", response_model=ChunkVisualization)
def get_chunk_visualization(document_id: UUID) -> ChunkVisualization:
    """Return a graph-friendly document and chunk visualization."""
    visualization = get_chunk_service().get_visualization(document_id)
    if visualization.statistics.total_chunks == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No chunks were found for this document.",
        )
    return visualization

