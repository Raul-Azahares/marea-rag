"""How the API hands work to the background worker.

The API only knows this interface, never Celery tasks: it publishes by task *name*, so the
API process does not import worker code. Tests swap in an in-memory implementation.
"""

import uuid
from typing import Protocol

from kombu.exceptions import OperationalError

from app.core.logging import get_logger
from app.worker.celery_app import INGEST_QUEUE, INGEST_TASK, celery_app

logger = get_logger(__name__)

# Fail fast when the broker is down: the upload request must not hang. Nothing is lost,
# because the document row stays `pending` and the reconciler enqueues it later.
_PUBLISH_RETRY_POLICY = {
    "max_retries": 2,
    "interval_start": 0,
    "interval_step": 0.3,
    "interval_max": 0.5,
}


class TaskQueue(Protocol):
    def enqueue_ingestion(self, document_id: uuid.UUID) -> bool:
        """Publish an ingestion job. Returns False if the broker is unreachable."""
        ...


class CeleryTaskQueue:
    def enqueue_ingestion(self, document_id: uuid.UUID) -> bool:
        try:
            celery_app.send_task(
                INGEST_TASK,
                args=[str(document_id)],
                queue=INGEST_QUEUE,
                retry=True,
                retry_policy=_PUBLISH_RETRY_POLICY,
            )
        except (OperationalError, OSError) as exc:
            logger.warning(
                "enqueue_failed",
                document_id=str(document_id),
                error_type=type(exc).__name__,
            )
            return False
        logger.info("ingestion_enqueued", document_id=str(document_id))
        return True
