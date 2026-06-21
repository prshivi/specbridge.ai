from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import get_settings
from app.core.exceptions import (
    DocumentChunksNotFoundError,
    ExtractedRequirementsNotFoundError,
    RequirementExtractionError,
    RequirementExtractionNotConfiguredError,
    UnderstandingAgentError,
    UnderstandingAgentNotConfiguredError,
)
from app.models.requirement_extraction import (
    ExtractedRequirement,
    RequirementExtractionResult,
)
from app.services.requirement_extraction import RequirementExtractionService

router = APIRouter(tags=["requirement extraction"])


def get_requirement_extraction_service() -> RequirementExtractionService:
    return RequirementExtractionService(get_settings())


@router.post(
    "/agents/requirements/{document_id}",
    response_model=RequirementExtractionResult,
)
def run_requirement_extraction(
    document_id: UUID,
    force_refresh: bool = Query(default=False),
) -> RequirementExtractionResult:
    """Run RequirementExtractionAgent for one uploaded specification."""
    try:
        return get_requirement_extraction_service().run(
            document_id,
            force_refresh=force_refresh,
        )
    except DocumentChunksNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except (
        RequirementExtractionNotConfiguredError,
        UnderstandingAgentNotConfiguredError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except (RequirementExtractionError, UnderstandingAgentError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


@router.get(
    "/requirements/{document_id}",
    response_model=RequirementExtractionResult,
)
def list_extracted_requirements(
    document_id: UUID,
) -> RequirementExtractionResult:
    """Return all stored framework-extracted requirements."""
    try:
        return get_requirement_extraction_service().list(document_id)
    except ExtractedRequirementsNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.get(
    "/requirements/{document_id}/{requirement_id}",
    response_model=ExtractedRequirement,
)
def get_extracted_requirement(
    document_id: UUID,
    requirement_id: str,
) -> ExtractedRequirement:
    """Return one stored requirement with source traceability."""
    try:
        return get_requirement_extraction_service().get(
            document_id,
            requirement_id,
        )
    except ExtractedRequirementsNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
