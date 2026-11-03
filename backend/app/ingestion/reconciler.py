"""Safety net for work that fell through the cracks. Celery beat runs it every minute.

It re-enqueues:
* `pending` documents older than `stale_pending_after_s`: the broker was down at upload time
  (the row acts as an outbox), or the message was lost;
* `processing` documents whose advisory lock is free: their worker died mid-run.

Re-enqueuing is safe because ingestion is idempotent. Touching `updated_at` limits it to one
re-enqueue per document per staleness window, even during a long backlog.
"""

import uuid
from datetime import timedelta

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Document, DocumentStatus
from app.ingestion.pipeline import document_lock_key
from app.task_queue import TaskQueue


def reconcile(
    engine: Engine, queue: TaskQueue, settings: Settings, *, limit: int = 100
) -> dict[str, int]:
    # Compared with the database clock: no skew between worker and database hosts.
    stale_before = func.now() - timedelta(seconds=settings.stale_pending_after_s)
    with Session(engine) as session:
        pending = list(
            session.scalars(
                select(Document.id)
                .where(
                    Document.status == DocumentStatus.PENDING, Document.updated_at < stale_before
                )
                .order_by(Document.updated_at)
                .limit(limit)
            )
        )
        # Materialised first: the lock probes below run on this same session.
        processing = list(
            session.scalars(
                select(Document.id)
                .where(
                    Document.status == DocumentStatus.PROCESSING,
                    Document.updated_at < stale_before,
                )
                .order_by(Document.updated_at)
                .limit(limit)
            )
        )
        orphaned = [
            document_id for document_id in processing if _lock_is_free(session, document_id)
        ]

        enqueued = 0
        for document_id in (*pending, *orphaned):
            if not queue.enqueue_ingestion(document_id):
                break  # broker still down: the next run will try again
            session.execute(
                update(Document).where(Document.id == document_id).values(updated_at=func.now())
            )
            enqueued += 1
        session.commit()
    return {
        "stale_pending": len(pending),
        "orphaned_processing": len(orphaned),
        "enqueued": enqueued,
    }


def _lock_is_free(session: Session, document_id: uuid.UUID) -> bool:
    key = document_lock_key(document_id)
    if session.scalar(select(func.pg_try_advisory_lock(key))):
        session.scalar(select(func.pg_advisory_unlock(key)))
        return True
    return False
