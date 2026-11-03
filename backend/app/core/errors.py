"""Domain errors: a stable machine-readable code plus a user-facing message in Spanish.

The API turns them into `{"error": {"code", "message"}}` responses. The same codes are
stored in `documents.error_code` when an ingestion fails, so the UI can explain the failure.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    # Request / upload validation
    VALIDATION_ERROR = "VALIDATION_ERROR"
    EMPTY_FILE = "EMPTY_FILE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    # Resources and state
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    CHUNK_NOT_FOUND = "CHUNK_NOT_FOUND"
    INVALID_STATE = "INVALID_STATE"
    CONCURRENT_UPLOAD = "CONCURRENT_UPLOAD"
    # Ingestion failures (persisted on the document)
    PDF_CORRUPT = "PDF_CORRUPT"
    PDF_ENCRYPTED = "PDF_ENCRYPTED"
    PDF_NO_TEXT = "PDF_NO_TEXT"
    PDF_TOO_MANY_PAGES = "PDF_TOO_MANY_PAGES"
    FILE_MISSING = "FILE_MISSING"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    MAX_ATTEMPTS_EXCEEDED = "MAX_ATTEMPTS_EXCEEDED"
    # Infrastructure
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Base class for expected, user-explainable errors."""

    status_code = 400

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class PayloadTooLargeError(AppError):
    status_code = 413


class UnsupportedMediaTypeError(AppError):
    status_code = 415
