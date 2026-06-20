from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown resources."""
    yield


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        debug=settings.app_debug,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(api_router)
    return application


app = create_application()

