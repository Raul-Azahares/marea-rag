"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api.deps import get_chat_model, get_embedding_provider
from app.api.errors import register_exception_handlers
from app.api.middleware import MaxBodySizeMiddleware, TraceIdHeaderMiddleware
from app.api.routes import chunks, documents, health, query
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_async_engine

# Multipart framing (boundaries, part headers) on top of the file itself.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Fail at startup, not on the first request, on a provider misconfiguration
    # (e.g. an embedding size that does not match the vector column).
    get_embedding_provider()
    get_chat_model()
    yield
    await get_async_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(
        service=settings.otel_service_name or "marea-api",
        level=settings.log_level,
        json=settings.log_json,
    )

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
    for module in (documents, query, chunks):
        api_v1.include_router(module.router)
    app.include_router(api_v1)
    return app


app = create_app()
