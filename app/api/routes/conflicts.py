from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import get_settings
from app.core.exceptions import (
    DetectedConflictsNotFoundError,
    DocumentChunksNotFoundError,
    ExtractedRequirementsNotFoundError,
    FrameworkConflictDetectionError,
    FrameworkConflictNotConfiguredError,
    UnderstandingAgentError,
    UnderstandingAgentNotConfiguredError,
)
from app.models.conflict_detection import (
    ConflictDetectionAgentResult,
    DetectedConflict,
)
from app.services.conflict_detection import FrameworkConflictDetectionService

router = APIRouter(tags=["conflict detection"])


def get_framework_conflict_service() -> FrameworkConflictDetectionService:
    return FrameworkConflictDetectionService(get_settings())


@router.post(
    "/agents/conflicts/{document_id}",
    response_model=ConflictDetectionAgentResult,
)
def run_conflict_detection(
    document_id: UUID,
    force_refresh: bool = Query(default=False),
) -> ConflictDetectionAgentResult:
    """Run ConflictDetectionAgent against stored extracted requirements."""
    try:
        return get_framework_conflict_service().run(
            document_id,
            force_refresh=force_refresh,
        )
    except (DocumentChunksNotFoundError, ExtractedRequirementsNotFoundError) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except (
        FrameworkConflictNotConfiguredError,
        UnderstandingAgentNotConfiguredError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except (FrameworkConflictDetectionError, UnderstandingAgentError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


@router.get(
    "/conflicts/{document_id}",
    response_model=ConflictDetectionAgentResult,
)
def list_detected_conflicts(document_id: UUID) -> ConflictDetectionAgentResult:
    """Return all stored conflicts for one specification."""
    try:
        return get_framework_conflict_service().list(document_id)
    except DetectedConflictsNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.get(
    "/conflicts/{document_id}/{conflict_id}",
    response_model=DetectedConflict,
)
def get_detected_conflict(
    document_id: UUID,
    conflict_id: str,
) -> DetectedConflict:
    """Return one conflict with complete traceability."""
    try:
        return get_framework_conflict_service().get(document_id, conflict_id)
    except DetectedConflictsNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
