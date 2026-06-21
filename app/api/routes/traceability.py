from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.core.config import get_settings
from app.core.exceptions import (
    AmbiguityDetectionError,
    AmbiguityDetectionNotConfiguredError,
    ArchitectureRecommendationError,
    ArchitectureRecommendationNotConfiguredError,
    AssumptionLedgerError,
    AssumptionLedgerNotConfiguredError,
    ConflictDetectionError,
    ConflictDetectionNotConfiguredError,
    DocumentChunksNotFoundError,
    EngineeringTranslationError,
    EngineeringTranslationNotConfiguredError,
    RequirementIntelligenceError,
    RequirementIntelligenceNotConfiguredError,
    UnderstandingAgentError,
    UnderstandingAgentNotConfiguredError,
)
from app.models.traceability import TraceabilityMatrix
from app.services.traceability import TraceabilityService

router = APIRouter(prefix="/traceability", tags=["traceability"])


def get_traceability_service() -> TraceabilityService:
    return TraceabilityService(get_settings())


@router.get("/{document_id}", response_model=TraceabilityMatrix)
def get_traceability(document_id: UUID) -> TraceabilityMatrix:
    """Return the complete requirement traceability matrix."""
    try:
        return get_traceability_service().build(document_id)
    except DocumentChunksNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except (
        ArchitectureRecommendationNotConfiguredError,
        EngineeringTranslationNotConfiguredError,
        AssumptionLedgerNotConfiguredError,
        ConflictDetectionNotConfiguredError,
        AmbiguityDetectionNotConfiguredError,
        RequirementIntelligenceNotConfiguredError,
        UnderstandingAgentNotConfiguredError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except (
        ArchitectureRecommendationError,
        EngineeringTranslationError,
        AssumptionLedgerError,
        ConflictDetectionError,
        AmbiguityDetectionError,
        RequirementIntelligenceError,
        UnderstandingAgentError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


@router.get("/{document_id}/export.csv")
def export_traceability_csv(document_id: UUID) -> Response:
    """Download the complete traceability matrix as UTF-8 CSV."""
    try:
        content = get_traceability_service().export_csv(document_id)
    except DocumentChunksNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except (
        ArchitectureRecommendationNotConfiguredError,
        EngineeringTranslationNotConfiguredError,
        AssumptionLedgerNotConfiguredError,
        ConflictDetectionNotConfiguredError,
        AmbiguityDetectionNotConfiguredError,
        RequirementIntelligenceNotConfiguredError,
        UnderstandingAgentNotConfiguredError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except (
        ArchitectureRecommendationError,
        EngineeringTranslationError,
        AssumptionLedgerError,
        ConflictDetectionError,
        AmbiguityDetectionError,
        RequirementIntelligenceError,
        UnderstandingAgentError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

    return Response(
        content="\ufeff" + content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="traceability-{document_id}.csv"'
            )
        },
    )

