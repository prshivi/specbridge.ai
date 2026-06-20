from fastapi import APIRouter

from app.models.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return the current service health."""
    return HealthResponse(status="healthy")

