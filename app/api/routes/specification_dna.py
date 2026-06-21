from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import get_settings
from app.core.exceptions import (
    DocumentChunksNotFoundError,
    UnderstandingAgentError,
    UnderstandingAgentNotConfiguredError,
)
from app.models.specification_dna import SpecificationDNAResult
from app.services.specification_dna import SpecificationDNAService

router = APIRouter(prefix="/specification-dna", tags=["specification DNA"])


def get_specification_dna_service() -> SpecificationDNAService:
    return SpecificationDNAService(get_settings())


@router.get("/{document_id}", response_model=SpecificationDNAResult)
def get_specification_dna(
    document_id: UUID,
    force_refresh: bool = Query(default=False),
) -> SpecificationDNAResult:
    """Generate or retrieve evidence-grounded Specification DNA."""
    try:
        return get_specification_dna_service().get(
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
