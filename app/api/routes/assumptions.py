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
    ExtractedRequirementsNotFoundError,
    MissingRequirementIssuesNotFoundError,
    RequirementIntelligenceError,
    RequirementIntelligenceNotConfiguredError,
    UnderstandingAgentError,
    UnderstandingAgentNotConfiguredError,
)
from app.models.assumption_ledger import (
    AssumptionStatusUpdate,
    FrameworkAssumptionLedgerResult,
    LedgerAssumption,
)
from app.models.assumptions import AssumptionLedgerResult
from app.services.assumptions import AssumptionLedgerService
from app.services.framework_assumptions import FrameworkAssumptionLedgerService

router = APIRouter(tags=["assumption ledger"])


def get_framework_assumption_service() -> FrameworkAssumptionLedgerService:
    return FrameworkAssumptionLedgerService(get_settings())


def get_assumption_service() -> AssumptionLedgerService:
    """Retain the pre-framework provider for legacy force-refresh clients."""
    return AssumptionLedgerService(get_settings())


@router.post(
    "/agents/assumptions/{document_id}",
    response_model=FrameworkAssumptionLedgerResult,
)
def run_assumption_ledger(
    document_id: UUID,
    force_refresh: bool = Query(default=False),
) -> FrameworkAssumptionLedgerResult:
    """Run AssumptionLedgerAgent and persist its fact/assumption ledger."""
    try:
        return get_framework_assumption_service().run(
            document_id,
            force_refresh=force_refresh,
        )
    except (
        DocumentChunksNotFoundError,
        ExtractedRequirementsNotFoundError,
        DetectedConflictsNotFoundError,
        MissingRequirementIssuesNotFoundError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except (
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
    "/assumptions/{document_id}",
    response_model=FrameworkAssumptionLedgerResult | AssumptionLedgerResult,
)
def list_assumptions(
    document_id: UUID,
    force_refresh: bool | None = Query(default=None),
) -> FrameworkAssumptionLedgerResult | AssumptionLedgerResult:
    """Return the framework ledger; support the former refresh query contract."""
    try:
        if force_refresh is not None:
            return get_assumption_service().get_ledger(
                document_id,
                force_refresh=force_refresh,
            )
        return get_framework_assumption_service().list(document_id)
    except AssumptionLedgerNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except (
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
    "/assumptions/{document_id}/{assumption_id}",
    response_model=LedgerAssumption,
)
def get_assumption(
    document_id: UUID,
    assumption_id: str,
) -> LedgerAssumption:
    """Return one assumption with complete traceability."""
    try:
        return get_framework_assumption_service().get(document_id, assumption_id)
    except AssumptionLedgerNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.patch(
    "/assumptions/{document_id}/{assumption_id}",
    response_model=LedgerAssumption,
)
def update_assumption_status(
    document_id: UUID,
    assumption_id: str,
    update: AssumptionStatusUpdate,
) -> LedgerAssumption:
    """Confirm or reject an open assumption."""
    try:
        return get_framework_assumption_service().update_status(
            document_id,
            assumption_id,
            update.status,
        )
    except AssumptionLedgerNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
