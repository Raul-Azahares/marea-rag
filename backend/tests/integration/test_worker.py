"""Ingestion through a real Celery worker consuming from the real Redis broker."""

import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio

from app.core.config import Settings, get_settings
from app.core.errors import ErrorCode
from app.db.models import DocumentStatus
from app.ingestion.pipeline import IngestionDeps
from app.main import create_app
from app.providers.base import ProviderUnavailableError
from app.providers.fake import HashingEmbeddingProvider
from app.worker import tasks
from app.worker.celery_app import INGEST_QUEUE, INGEST_TASK, celery_app
from tests.conftest import sample_pdf
from tests.fakes import FlakyEmbedder
from tests.integration.ingestion_helpers import add_document, load, wait_for

pytestmark = pytest.mark.integration

# Captured before any monkeypatching, so the replacement can delegate to the real one.
_real_build_ingestion_deps = tasks.build_ingestion_deps


def queue_length() -> int:
    with celery_app.connection_for_write() as connection:
        return int(connection.default_channel.client.llen(INGEST_QUEUE))


@pytest_asyncio.fixture
async def live_client(clean_database: None, worker: None) -> AsyncIterator[httpx.AsyncClient]:
    """API wired to the real broker (no queue override)."""
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def deps_with(embedder: Any, **overrides: Any) -> Callable[[Settings], IngestionDeps]:
    def build(settings: Settings) -> IngestionDeps:
        deps = _real_build_ingestion_deps(settings.model_copy(update=overrides))
        return IngestionDeps(
            engine=deps.engine, storage=deps.storage, embedder=embedder, settings=deps.settings
        )

    return build


async def test_uploaded_pdf_is_ingested_by_the_worker(live_client: httpx.AsyncClient) -> None:
    response = await live_client.post(
        "/api/v1/documents",
        files={
            "file": ("hogar.pdf", sample_pdf("marea-auto-condicionado-2025.pdf"), "application/pdf")
        },
    )
    assert response.status_code == 202
    assert response.json()["queued"] is True

    document = wait_for(uuid.UUID(response.json()["id"]), DocumentStatus.READY)

    assert document.chunk_count is not None
    assert document.chunk_count > 5
    detail = (await live_client.get(f"/api/v1/documents/{document.id}")).json()
    assert (detail["status"], detail["progress"], detail["page_count"]) == ("ready", 100, 5)


def test_poison_message_is_dropped_and_the_worker_keeps_working(
    clean_database: None, worker: None
) -> None:
    celery_app.send_task(INGEST_TASK, args=["not-a-uuid"], queue=INGEST_QUEUE)
    celery_app.send_task(INGEST_TASK, args=[{"unexpected": "shape"}], queue=INGEST_QUEUE)
    document_id = add_document(sample_pdf("marea-auto-condicionado-2025.pdf"))
    celery_app.send_task(INGEST_TASK, args=[str(document_id)], queue=INGEST_QUEUE)

    wait_for(document_id, DocumentStatus.READY)
    assert queue_length() == 0  # rejected without requeue: not redelivered forever


def test_duplicate_messages_ingest_once(clean_database: None, worker: None) -> None:
    document_id = add_document(sample_pdf("marea-auto-condicionado-2025.pdf"))
    for _ in range(3):
        celery_app.send_task(INGEST_TASK, args=[str(document_id)], queue=INGEST_QUEUE)

    document = wait_for(document_id, DocumentStatus.READY)
    time.sleep(1)  # let the duplicates drain

    assert load(document_id).attempts == 1
    assert load(document_id).chunk_count == document.chunk_count


def test_transient_failures_are_retried_with_backoff(
    clean_database: None, worker: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    flaky = FlakyEmbedder(
        HashingEmbeddingProvider(768), failures=2, error=ProviderUnavailableError("503")
    )
    monkeypatch.setattr(tasks, "build_ingestion_deps", deps_with(flaky))
    document_id = add_document(sample_pdf("marea-auto-condicionado-2025.pdf"))

    celery_app.send_task(INGEST_TASK, args=[str(document_id)], queue=INGEST_QUEUE)

    document = wait_for(document_id, DocumentStatus.READY)
    assert document.attempts == 3  # 1 + 2 retries
    assert document.error_message is None  # the "retrying" note is cleared on success


def test_exhausted_retries_mark_the_document_failed(
    clean_database: None, worker: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    down = FlakyEmbedder(
        HashingEmbeddingProvider(768), failures=99, error=ProviderUnavailableError("503")
    )
    monkeypatch.setattr(tasks, "build_ingestion_deps", deps_with(down, ingest_max_retries=2))
    document_id = add_document(sample_pdf("marea-auto-condicionado-2025.pdf"))

    celery_app.send_task(INGEST_TASK, args=[str(document_id)], queue=INGEST_QUEUE)

    document = wait_for(document_id, DocumentStatus.FAILED)
    assert document.error_code == ErrorCode.PROVIDER_UNAVAILABLE
    assert document.attempts == 3
    assert down.calls == 3
    assert get_settings().ingest_max_retries == 5  # the override did not leak
