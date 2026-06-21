from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import get_settings
from app.core.exceptions import (
    AmbiguityDetectionError,
    AmbiguityDetectionNotConfiguredError,
    ArchitectureBlueprintNotFoundError,
    ArchitectureRecommendationError,
    ArchitectureRecommendationNotConfiguredError,
    AssumptionLedgerError,
    AssumptionLedgerNotConfiguredError,
    AssumptionLedgerNotFoundError,
    ConflictDetectionError,
    ConflictDetectionNotConfiguredError,
    DocumentChunksNotFoundError,
    EngineeringBlueprintNotFoundError,
    EngineeringTranslationError,
    EngineeringTranslationNotConfiguredError,
    ExtractedRequirementsNotFoundError,
    RequirementIntelligenceError,
    RequirementIntelligenceNotConfiguredError,
    UnderstandingAgentError,
    UnderstandingAgentNotConfiguredError,
)
from app.models.architecture import ArchitectureRecommendationResult
from app.models.architecture_blueprint import (
    ArchitectureBlueprintResult,
    ArchitectureDiagramCollection,
)
from app.services.architecture import ArchitectureRecommendationService
from app.services.framework_architecture import (
    FrameworkArchitectureRecommendationService,
)

router = APIRouter(tags=["architecture"])


def get_framework_architecture_service() -> (
    FrameworkArchitectureRecommendationService
):
    return FrameworkArchitectureRecommendationService(get_settings())


def get_architecture_service() -> ArchitectureRecommendationService:
    """Retain the pre-framework architecture service for legacy consumers."""
    return ArchitectureRecommendationService(get_settings())


@router.post(
    "/agents/architecture/{document_id}",
    response_model=ArchitectureBlueprintResult,
)
def run_architecture_agent(
    document_id: UUID,
    force_refresh: bool = Query(default=False),
) -> ArchitectureBlueprintResult:
    """Generate the framework-native Architecture Blueprint."""
    try:
        return get_framework_architecture_service().run(
            document_id,
            force_refresh=force_refresh,
        )
    except (
        DocumentChunksNotFoundError,
        ExtractedRequirementsNotFoundError,
        AssumptionLedgerNotFoundError,
        EngineeringBlueprintNotFoundError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except (
        ArchitectureRecommendationNotConfiguredError,
        EngineeringTranslationNotConfiguredError,
        AssumptionLedgerNotConfiguredError,
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
        AmbiguityDetectionError,
        RequirementIntelligenceError,
        UnderstandingAgentError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


@router.get(
    "/architecture/{document_id}",
    response_model=ArchitectureBlueprintResult | ArchitectureRecommendationResult,
)
def get_architecture_recommendations(
    document_id: UUID,
    force_refresh: bool | None = Query(default=None),
) -> ArchitectureBlueprintResult | ArchitectureRecommendationResult:
    """Return the framework blueprint while preserving the legacy query path."""
    try:
        if force_refresh is not None:
            return get_architecture_service().recommend(
                document_id,
                force_refresh=force_refresh,
            )
        return get_framework_architecture_service().get(document_id)
    except ArchitectureBlueprintNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
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


@router.get(
    "/architecture/{document_id}/diagram",
    response_model=ArchitectureDiagramCollection,
)
def get_architecture_diagrams(
    document_id: UUID,
) -> ArchitectureDiagramCollection:
    """Return all five traceable Mermaid architecture diagrams."""
    try:
        return get_framework_architecture_service().diagrams(document_id)
    except ArchitectureBlueprintNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
