"""Shared test configuration.

Environment variables are set *before* anything from `app` is imported, so cached settings,
engines and the Celery app pick them up. Integration tests need the throwaway infrastructure
(`make test-infra`: Postgres on 55432, Redis on 56379), which matches the settings' defaults.
"""

import io
import os
import tempfile
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("OTEL_ENABLED", "false")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("UPLOAD_DIR", tempfile.mkdtemp(prefix="marea-test-uploads-"))
os.environ.setdefault("INGEST_RETRY_BASE_DELAY_S", "0")  # retries without waiting

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from pypdf import PdfWriter
from sqlalchemy import text

from app.api.deps import get_task_queue
from app.core.config import get_settings
from app.db.session import get_sync_engine
from app.main import create_app
from tests.fakes import RecordingQueue

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = Path(BACKEND_DIR).parent / "samples"


def sample_pdf(name: str) -> bytes:
    return (SAMPLES_DIR / name).read_bytes()


# ------------------------------------------------------------------------ PDF helpers
@pytest.fixture
def make_blank_pdf() -> Callable[[], bytes]:
    """Valid PDFs with unique bytes (so each one gets its own SHA-256)."""

    def _make() -> bytes:
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_metadata({"/Title": f"test-{uuid.uuid4()}"})
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    return _make


# ------------------------------------------------------------------------- database
@pytest.fixture(scope="session")
def migrated_database() -> None:
    """Fresh schema for the test session: drop everything, then run the real migrations."""
    engine = get_sync_engine()
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    except Exception as exc:  # pragma: no cover - only when the infrastructure is missing
        pytest.fail(f"Test database unreachable ({exc!r}). Start it with `make test-infra`.")
    config = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(config, "head")


@pytest.fixture
def clean_database(migrated_database: None) -> None:
    with get_sync_engine().begin() as connection:
        connection.execute(text("TRUNCATE documents, chunks CASCADE"))


# ---------------------------------------------------------------------------- API
@pytest.fixture
def queue() -> RecordingQueue:
    return RecordingQueue()


@pytest.fixture
def app(clean_database: None, queue: RecordingQueue) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_task_queue] = lambda: queue
    return application


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
