from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import get_settings
from app.core.exceptions import (
    AmbiguityDetectionError,
    AmbiguityDetectionNotConfiguredError,
    DocumentChunksNotFoundError,
    RequirementIntelligenceError,
    RequirementIntelligenceNotConfiguredError,
    UnderstandingAgentError,
    UnderstandingAgentNotConfiguredError,
)
from app.models.ambiguity import AmbiguityDetectionResult
from app.services.ambiguity import AmbiguityDetectionService

router = APIRouter(prefix="/ambiguities", tags=["ambiguity"])


def get_ambiguity_service() -> AmbiguityDetectionService:
    return AmbiguityDetectionService(get_settings())


@router.get("/{document_id}", response_model=AmbiguityDetectionResult)
def get_ambiguities(
    document_id: UUID,
    force_refresh: bool = Query(default=False),
) -> AmbiguityDetectionResult:
    """Return stored ambiguity analysis, running it on the first request."""
    try:
        return get_ambiguity_service().detect(
            document_id,
            force_refresh=force_refresh,
        )
    except DocumentChunksNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except (
        AmbiguityDetectionNotConfiguredError,
        RequirementIntelligenceNotConfiguredError,
        UnderstandingAgentNotConfiguredError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except (
        AmbiguityDetectionError,
        RequirementIntelligenceError,
        UnderstandingAgentError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

