from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.core.exceptions import (
    DocumentChunksNotFoundError,
    KnowledgeGraphNotFoundError,
)
from app.models.knowledge import (
    KnowledgeBuildResult,
    KnowledgeGraph,
    KnowledgeModel,
)
from app.services.knowledge import KnowledgeGraphService

router = APIRouter(prefix="/knowledge", tags=["knowledge graph"])


def get_knowledge_service() -> KnowledgeGraphService:
    return KnowledgeGraphService(get_settings())


@router.post(
    "/build/{document_id}",
    response_model=KnowledgeBuildResult,
    status_code=status.HTTP_201_CREATED,
)
def build_knowledge_graph(document_id: UUID) -> KnowledgeBuildResult:
    """Deterministically rebuild and store a specification knowledge graph."""
    try:
        return get_knowledge_service().build(document_id)
    except DocumentChunksNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.get("/{document_id}", response_model=KnowledgeModel)
def get_knowledge_model(document_id: UUID) -> KnowledgeModel:
    """Return persisted entities and relationships for one specification."""
    try:
        return get_knowledge_service().get(document_id)
    except KnowledgeGraphNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.get("/graph/{document_id}", response_model=KnowledgeGraph)
def get_knowledge_graph(document_id: UUID) -> KnowledgeGraph:
    """Return the persisted knowledge model as graph-oriented JSON."""
    try:
        return get_knowledge_service().get_graph(document_id)
    except KnowledgeGraphNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
