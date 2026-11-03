"""Celery application: broker, queues and reliability settings.

Queue design:
  * `ingest`      long-running, retryable document ingestion
  * `maintenance` periodic reconciliation (beat)
Keeping them apart means an ingestion backlog never delays the reconciler, and each queue
can get its own worker pool.

Reliability: messages are acknowledged *after* the task finishes (acks_late), and requeued
if the worker process dies. A message can therefore be delivered more than once, so every
task is idempotent. Task state lives in PostgreSQL, so there is no result backend.
"""

from celery import Celery
from kombu import Queue

from app.core.config import get_settings

INGEST_QUEUE = "ingest"
MAINTENANCE_QUEUE = "maintenance"
INGEST_TASK = "marea.ingest_document"
RECONCILE_TASK = "marea.reconcile_documents"


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery("marea", broker=settings.redis_url, include=["app.worker.tasks"])
    app.conf.update(
        # JSON only. Accepting pickle would let a forged message execute code.
        task_serializer="json",
        accept_content=["json"],
        task_ignore_result=True,
        # --- At-least-once delivery ---------------------------------------------------
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        # Long tasks: take one message at a time so work spreads evenly across workers.
        worker_prefetch_multiplier=1,
        task_soft_time_limit=settings.ingest_soft_time_limit_s,
        task_time_limit=settings.ingest_time_limit_s,
        # Redis redelivers a message that was not acked within this window. It must exceed
        # the hard time limit, or a slow-but-healthy task would be delivered twice.
        broker_transport_options={"visibility_timeout": 900},
        broker_connection_retry_on_startup=True,
        # --- Routing ----------------------------------------------------------------------
        task_default_queue=INGEST_QUEUE,
        task_queues=[Queue(INGEST_QUEUE), Queue(MAINTENANCE_QUEUE)],
        task_routes={
            INGEST_TASK: {"queue": INGEST_QUEUE},
            RECONCILE_TASK: {"queue": MAINTENANCE_QUEUE},
        },
        beat_schedule={
            "reconcile-documents": {
                "task": RECONCILE_TASK,
                "schedule": float(settings.reconcile_interval_s),
                # A stale reconcile run is useless: drop it instead of piling them up.
                "options": {"expires": settings.reconcile_interval_s},
            }
        },
        # --- Operability --------------------------------------------------------------------
        worker_hijack_root_logger=False,  # we configure structured logging ourselves
        worker_send_task_events=True,  # task events for Flower
        task_send_sent_event=True,
        timezone="UTC",
    )
    return app


celery_app = create_celery_app()

# Registers the worker's process-level hooks (logging, connection pools after fork).
from app.worker import signals  # noqa: E402, F401
