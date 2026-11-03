"""Process-level hooks for Celery workers and beat."""

from typing import Any

from celery import signals

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_sync_engine


@signals.setup_logging.connect
def _setup_logging(**_: Any) -> None:
    # Connecting to this signal stops Celery from installing its own logging handlers.
    settings = get_settings()
    configure_logging(
        service=settings.otel_service_name or "marea-worker",
        level=settings.log_level,
        json=settings.log_json,
    )


@signals.worker_process_init.connect
def _reset_connection_pool(**_: Any) -> None:
    """A forked child must never reuse sockets from the parent's connection pool."""
    get_sync_engine().dispose(close=False)
