from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import get_settings
from app.core.exceptions import (
    DetectedConflictsNotFoundError,
    DocumentChunksNotFoundError,
    ExtractedRequirementsNotFoundError,
    MissingRequirementDetectionError,
    MissingRequirementIssuesNotFoundError,
    MissingRequirementNotConfiguredError,
    UnderstandingAgentError,
    UnderstandingAgentNotConfiguredError,
)
from app.models.missing_requirements import (
    MissingRequirementDetectionResult,
    MissingRequirementIssue,
)
from app.services.missing_requirement_detection import (
    MissingRequirementDetectionService,
)

router = APIRouter(tags=["missing requirement detection"])


def get_missing_requirement_service() -> MissingRequirementDetectionService:
    return MissingRequirementDetectionService(get_settings())


@router.post(
    "/agents/missing-requirements/{document_id}",
    response_model=MissingRequirementDetectionResult,
)
def run_missing_requirement_detection(
    document_id: UUID,
    force_refresh: bool = Query(default=False),
) -> MissingRequirementDetectionResult:
    """Run contextual missing requirement detection."""
    try:
        return get_missing_requirement_service().run(
            document_id,
            force_refresh=force_refresh,
        )
    except (
        DocumentChunksNotFoundError,
        ExtractedRequirementsNotFoundError,
        DetectedConflictsNotFoundError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except (
        MissingRequirementNotConfiguredError,
        UnderstandingAgentNotConfiguredError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except (MissingRequirementDetectionError, UnderstandingAgentError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


@router.get(
    "/missing-requirements/{document_id}",
    response_model=MissingRequirementDetectionResult,
)
def list_missing_requirements(
    document_id: UUID,
) -> MissingRequirementDetectionResult:
    """Return all stored contextual requirement gaps."""
    try:
        return get_missing_requirement_service().list(document_id)
    except MissingRequirementIssuesNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.get(
    "/missing-requirements/{document_id}/{missing_requirement_id}",
    response_model=MissingRequirementIssue,
)
def get_missing_requirement(
    document_id: UUID,
    missing_requirement_id: str,
) -> MissingRequirementIssue:
    """Return one missing requirement issue with traceability."""
    try:
        return get_missing_requirement_service().get(
            document_id,
            missing_requirement_id,
        )
    except MissingRequirementIssuesNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
