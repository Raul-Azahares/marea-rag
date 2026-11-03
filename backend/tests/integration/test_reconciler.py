import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Document, DocumentStatus
from app.db.session import get_sync_engine
from app.ingestion.pipeline import document_lock_key
from app.ingestion.reconciler import reconcile
from tests.fakes import RecordingQueue
from tests.integration.ingestion_helpers import add_document, load

pytestmark = pytest.mark.integration


def age(document_id: uuid.UUID, minutes: int) -> None:
    with Session(get_sync_engine()) as session, session.begin():
        session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(updated_at=func.now() - timedelta(minutes=minutes))
        )


def run(queue: RecordingQueue) -> dict[str, int]:
    return reconcile(get_sync_engine(), queue, get_settings())


def test_stale_pending_documents_are_re_enqueued_once(clean_database: None) -> None:
    stale = add_document(b"%PDF-stale")
    fresh = add_document(b"%PDF-fresh")
    age(stale, minutes=10)
    queue = RecordingQueue()

    report = run(queue)
    second = run(queue)  # `updated_at` was touched: not re-enqueued again right away

    assert queue.enqueued == [stale]
    assert report == {"stale_pending": 1, "orphaned_processing": 0, "enqueued": 1}
    assert second["enqueued"] == 0
    assert load(fresh).status is DocumentStatus.PENDING


def test_processing_documents_are_re_enqueued_only_if_their_worker_died(
    clean_database: None,
) -> None:
    orphan = add_document(b"%PDF-orphan", status=DocumentStatus.PROCESSING)
    alive = add_document(b"%PDF-alive", status=DocumentStatus.PROCESSING)
    age(orphan, minutes=10)
    age(alive, minutes=10)
    queue = RecordingQueue()

    with get_sync_engine().connect() as live_worker:  # still holds its lock
        live_worker.scalar(select(func.pg_advisory_lock(document_lock_key(alive))))
        live_worker.commit()
        report = run(queue)
        live_worker.scalar(select(func.pg_advisory_unlock(document_lock_key(alive))))
        live_worker.commit()

    assert queue.enqueued == [orphan]
    assert report["orphaned_processing"] == 1


def test_broker_still_down_enqueues_nothing(clean_database: None) -> None:
    age(add_document(b"%PDF-stale"), minutes=10)
    queue = RecordingQueue()
    queue.available = False

    assert run(queue)["enqueued"] == 0
