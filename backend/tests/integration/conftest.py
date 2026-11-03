import uuid
from collections.abc import Iterator

import pytest
from celery.contrib.testing.worker import start_worker
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_sync_engine
from app.ingestion.pipeline import IngestionDeps, Outcome, run_ingestion
from app.providers.fake import HashingEmbeddingProvider
from app.worker.celery_app import celery_app
from tests.conftest import sample_pdf
from tests.integration.ingestion_helpers import add_document, storage

HOGAR_TITLE = "Marea Hogar Plus · Condicionado General"


@pytest.fixture(scope="module")
def corpus(migrated_database: None) -> dict[str, uuid.UUID]:
    """The sample library, indexed with the fake embedder: home 2025 superseded by home 2026,
    the motor policy and the adversarial annex. Built once per test module."""
    with get_sync_engine().begin() as connection:
        connection.execute(text("TRUNCATE documents, chunks CASCADE"))
    deps = IngestionDeps(
        engine=get_sync_engine(),
        storage=storage(),
        embedder=HashingEmbeddingProvider(768),
        settings=get_settings(),
    )
    ids: dict[str, uuid.UUID] = {}
    ids["hogar_v1"] = add_document(
        sample_pdf("marea-hogar-condicionado-2025.pdf"), title=HOGAR_TITLE
    )
    ids["hogar_v2"] = add_document(
        sample_pdf("marea-hogar-condicionado-2026.pdf"),
        title=HOGAR_TITLE,
        lineage_id=ids["hogar_v1"],
        version=2,
    )
    ids["auto"] = add_document(
        sample_pdf("marea-auto-condicionado-2025.pdf"), title="Marea Auto · Condicionado General"
    )
    ids["annex"] = add_document(
        sample_pdf("adversarial/anexo-condiciones-especiales.pdf"),
        title="Anexo de Condiciones Especiales",
    )
    for document_id in ids.values():  # in insertion order: v1 is superseded by v2
        assert run_ingestion(document_id, deps).outcome is Outcome.READY
    return ids


@pytest.fixture(scope="module")
def worker(migrated_database: None) -> Iterator[None]:
    """A real Celery worker (solo pool, in this process) consuming from the test Redis."""
    celery_app.control.purge()
    with start_worker(
        celery_app, pool="solo", concurrency=1, perform_ping_check=False, shutdown_timeout=20
    ):
        yield
