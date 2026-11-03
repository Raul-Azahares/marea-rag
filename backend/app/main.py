"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api.errors import register_exception_handlers
from app.api.middleware import MaxBodySizeMiddleware, TraceIdHeaderMiddleware
from app.api.routes import documents, health
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_async_engine

# Multipart framing (boundaries, part headers) on top of the file itself.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await get_async_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(service="api", level=settings.log_level, json=settings.log_json)

    app = FastAPI(
        title="Marea Seguros · Asistente de pólizas",
        version="0.1.0",
        # Under /api, so the docs are reachable through the frontend's /api proxy too.
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        MaxBodySizeMiddleware, max_bytes=settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES
    )
    app.add_middleware(TraceIdHeaderMiddleware)
    register_exception_handlers(app)

    app.include_router(health.router)
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(documents.router)
    app.include_router(api_v1)
    return app


app = create_app()
