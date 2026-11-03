"""Celery tasks: thin adapters around app.ingestion.

They validate the message, build the dependencies and decide whether to retry. The work
itself lives in app.ingestion, which is testable without Celery.
"""

import random
import uuid
from collections.abc import Callable
from typing import Any

from celery import Task
from celery.exceptions import Reject, SoftTimeLimitExceeded
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import InterfaceError, OperationalError

from app.core.config import Settings, get_settings
from app.core.errors import ErrorCode
from app.core.logging import get_logger
from app.db.session import get_sync_engine
from app.ingestion.errors import TransientIngestionError
from app.ingestion.pipeline import IngestionDeps, mark_failed, note_retry, run_ingestion
from app.ingestion.reconciler import reconcile
from app.providers.factory import build_embedding_provider
from app.storage import LocalFileStorage
from app.task_queue import CeleryTaskQueue
from app.worker.celery_app import INGEST_TASK, RECONCILE_TASK, celery_app

logger = get_logger(__name__)

# Worth retrying: provider timeouts and rate limits (raised by the pipeline as
# TransientIngestionError) and a database that is down or restarting.
TRANSIENT_ERRORS = (TransientIngestionError, OperationalError, InterfaceError)


class IngestPayload(BaseModel):
    document_id: uuid.UUID


def build_ingestion_deps(settings: Settings) -> IngestionDeps:
    """Composition root of the worker. Tests replace it to inject fakes."""
    return IngestionDeps(
        engine=get_sync_engine(),
        storage=LocalFileStorage(settings.upload_dir),
        embedder=build_embedding_provider(settings),
        settings=settings,
    )


def backoff_delay(retries: int, *, base: float, cap: float = 300.0) -> float:
    """Exponential backoff with +-50% jitter, so many failing documents don't retry in sync."""
    return min(cap, base * 2.0**retries) * random.uniform(0.5, 1.5)  # noqa: S311 - jitter, not crypto


@celery_app.task(name=INGEST_TASK, bind=True, max_retries=None)
def ingest_document(self: "Task[Any, Any]", document_id: Any) -> dict[str, Any]:
    try:
        payload = IngestPayload(document_id=document_id)
    except ValidationError:
        # Poison message: it can never succeed. Reject it without requeueing, so it is
        # dropped rather than redelivered forever. Log its shape, never its content.
        logger.error(
            "poison_message_rejected",
            task=INGEST_TASK,
            reason="invalid_payload",
            payload_type=type(document_id).__name__,
        )
        raise Reject("invalid payload", requeue=False) from None

    deps = build_ingestion_deps(get_settings())
    try:
        result = run_ingestion(payload.document_id, deps)
    except SoftTimeLimitExceeded:
        mark_failed(
            deps.engine,
            payload.document_id,
            ErrorCode.TIMEOUT,
            "La ingesta superó el tiempo máximo permitido.",
        )
        return {"outcome": "failed", "error_code": ErrorCode.TIMEOUT}
    except TRANSIENT_ERRORS as exc:
        return _retry_or_fail(self, payload.document_id, deps, exc)
    return {
        "outcome": result.outcome,
        "chunk_count": result.chunk_count,
        "page_count": result.page_count,
        "error_code": result.error_code,
    }


def _retry_or_fail(
    task: "Task[Any, Any]", document_id: uuid.UUID, deps: IngestionDeps, exc: Exception
) -> dict[str, Any]:
    settings = deps.settings
    retries = task.request.retries
    code = exc.code if isinstance(exc, TransientIngestionError) else ErrorCode.DATABASE_UNAVAILABLE
    if retries >= settings.ingest_max_retries:
        logger.error(
            "ingestion_retries_exhausted",
            document_id=str(document_id),
            error_code=code,
            retries=retries,
        )
        message = (
            f"Servicio no disponible tras {retries} reintentos. Puedes reintentarlo más tarde."
        )
        _best_effort(lambda: mark_failed(deps.engine, document_id, code, message), document_id)
        return {"outcome": "failed", "error_code": code}

    delay = backoff_delay(retries, base=settings.ingest_retry_base_delay_s)
    logger.warning(
        "ingestion_retry_scheduled",
        document_id=str(document_id),
        error_code=code,
        error_type=type(exc).__name__,
        retry=retries + 1,
        delay_s=round(delay, 1),
    )
    note = (
        f"Servicio externo no disponible: reintento {retries + 1} de "
        f"{settings.ingest_max_retries} en {delay:.0f} s."
    )
    _best_effort(lambda: note_retry(deps.engine, document_id, note), document_id)
    raise task.retry(exc=exc, countdown=delay)


def _best_effort(update_state: Callable[[], None], document_id: uuid.UUID) -> None:
    """Record state if the database lets us. If it is down too, the reconciler cleans up later."""
    try:
        update_state()
    except Exception as exc:
        logger.warning(
            "state_update_failed", document_id=str(document_id), error_type=type(exc).__name__
        )


@celery_app.task(name=RECONCILE_TASK)
def reconcile_documents() -> dict[str, int]:
    report = reconcile(get_sync_engine(), CeleryTaskQueue(), get_settings())
    if report["enqueued"]:
        logger.info("reconcile_enqueued", **report)
    return report
