from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import get_settings
from app.core.exceptions import (
    AmbiguityDetectionError,
    AmbiguityDetectionNotConfiguredError,
    AssumptionLedgerError,
    AssumptionLedgerNotConfiguredError,
    AssumptionLedgerNotFoundError,
    DetectedConflictsNotFoundError,
    DocumentChunksNotFoundError,
    EngineeringBlueprintNotFoundError,
    EngineeringTranslationError,
    EngineeringTranslationNotConfiguredError,
    ExtractedRequirementsNotFoundError,
    MissingRequirementIssuesNotFoundError,
    RequirementIntelligenceError,
    RequirementIntelligenceNotConfiguredError,
    UnderstandingAgentError,
    UnderstandingAgentNotConfiguredError,
)
from app.models.engineering import EngineeringTranslationResult
from app.models.engineering_blueprint import (
    BlueprintArtifact,
    EngineeringBlueprintResult,
)
from app.services.business_to_engineering import (
    BusinessToEngineeringTranslationService,
)
from app.services.translator import BusinessToEngineeringTranslatorService

router = APIRouter(tags=["engineering"])


def get_business_to_engineering_service() -> (
    BusinessToEngineeringTranslationService
):
    return BusinessToEngineeringTranslationService(get_settings())


def get_translator_service() -> BusinessToEngineeringTranslatorService:
    """Retain the pre-framework translator for existing downstream callers."""
    return BusinessToEngineeringTranslatorService(get_settings())


@router.post(
    "/agents/business-to-engineering/{document_id}",
    response_model=EngineeringBlueprintResult,
)
def run_business_to_engineering(
    document_id: UUID,
    force_refresh: bool = Query(default=False),
) -> EngineeringBlueprintResult:
    """Generate the framework-native Engineering Blueprint."""
    try:
        return get_business_to_engineering_service().run(
            document_id,
            force_refresh=force_refresh,
        )
    except (
        DocumentChunksNotFoundError,
        ExtractedRequirementsNotFoundError,
        DetectedConflictsNotFoundError,
        MissingRequirementIssuesNotFoundError,
        AssumptionLedgerNotFoundError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except (
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
    "/engineering/{document_id}",
    response_model=EngineeringBlueprintResult | EngineeringTranslationResult,
)
def get_engineering_blueprint(
    document_id: UUID,
    force_refresh: bool | None = Query(default=None),
) -> EngineeringBlueprintResult | EngineeringTranslationResult:
    """Return the stored blueprint; preserve the former refresh query contract."""
    try:
        if force_refresh is not None:
            return get_translator_service().translate(
                document_id,
                force_refresh=force_refresh,
            )
        return get_business_to_engineering_service().list(document_id)
    except EngineeringBlueprintNotFoundError as error:
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
    "/engineering/{document_id}/{artifact_id}",
    response_model=BlueprintArtifact,
)
def get_engineering_artifact(
    document_id: UUID,
    artifact_id: str,
) -> BlueprintArtifact:
    """Return one engineering artifact with complete upstream traceability."""
    try:
        return get_business_to_engineering_service().get(
            document_id,
            artifact_id,
        )
    except EngineeringBlueprintNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
