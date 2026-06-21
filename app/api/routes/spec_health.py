from uuid import UUID

from fastapi import APIRouter, HTTPException, status

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
from app.models.spec_health import SpecHealthDashboard
from app.services.spec_health import SpecHealthService

router = APIRouter(prefix="/spec-health", tags=["spec health"])


def get_spec_health_service() -> SpecHealthService:
    return SpecHealthService(get_settings())


@router.get("/{document_id}", response_model=SpecHealthDashboard)
def get_spec_health(document_id: UUID) -> SpecHealthDashboard:
    """Return an explainable readiness dashboard for one specification."""
    try:
        return get_spec_health_service().generate(document_id)
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
