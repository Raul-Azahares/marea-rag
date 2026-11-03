"""Ingestion failures, split by what a retry can achieve."""

from app.core.errors import ErrorCode


class IngestionError(Exception):
    """Permanent: retrying gives the same result (corrupt PDF, no text layer...).
    The document is marked FAILED immediately."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TransientIngestionError(Exception):
    """Temporary (provider timeout or rate limit...): the Celery task retries it
    with exponential backoff."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
