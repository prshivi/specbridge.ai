from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import get_settings
from app.core.exceptions import (
    DocumentChunksNotFoundError,
    UnderstandingAgentError,
    UnderstandingAgentNotConfiguredError,
)
from app.models.understanding import SpecificationUnderstandingResult
from app.services.understanding import SpecificationUnderstandingService

router = APIRouter(prefix="/documents", tags=["understanding"])


def get_understanding_service() -> SpecificationUnderstandingService:
    return SpecificationUnderstandingService(get_settings())


@router.post(
    "/{document_id}/understanding",
    response_model=SpecificationUnderstandingResult,
)
def understand_specification(
    document_id: UUID,
    force_refresh: bool = Query(default=False),
) -> SpecificationUnderstandingResult:
    """Analyze the complete uploaded specification and cache the result."""
    try:
        return get_understanding_service().understand(
            document_id,
            force_refresh=force_refresh,
        )
    except DocumentChunksNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except UnderstandingAgentNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except UnderstandingAgentError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

