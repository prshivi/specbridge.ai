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
    DeveloperCopilotError,
    DeveloperCopilotNotConfiguredError,
    DocumentChunksNotFoundError,
    EngineeringTranslationError,
    EngineeringTranslationNotConfiguredError,
    RequirementIntelligenceError,
    RequirementIntelligenceNotConfiguredError,
    UnderstandingAgentError,
    UnderstandingAgentNotConfiguredError,
)
from app.models.copilot import DeveloperCopilotResponse, DeveloperQuestion
from app.services.copilot import DeveloperCopilotService

router = APIRouter(prefix="/copilot", tags=["copilot"])


def get_copilot_service() -> DeveloperCopilotService:
    return DeveloperCopilotService(get_settings())


@router.post("/{document_id}/ask", response_model=DeveloperCopilotResponse)
def ask_developer_copilot(
    document_id: UUID,
    request: DeveloperQuestion,
) -> DeveloperCopilotResponse:
    """Answer a developer question from approved specification sources."""
    try:
        return get_copilot_service().ask(document_id, request.question)
    except DocumentChunksNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except (
        DeveloperCopilotNotConfiguredError,
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
        DeveloperCopilotError,
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

