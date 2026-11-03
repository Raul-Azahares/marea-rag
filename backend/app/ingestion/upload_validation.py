"""Validation of an uploaded file *before* anything is stored or enqueued.

Rules: extension `.pdf`, a plausible declared content type, PDF magic bytes, not empty, and
within the size limit. The magic bytes are authoritative: the extension and the content type
come from the client and are trivially spoofed. Structural problems (corrupt, encrypted,
image-only) are only detectable by parsing, so the worker handles them.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO

from app.core.errors import (
    AppError,
    ErrorCode,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)

PDF_MAGIC = b"%PDF-"
# The PDF spec tolerates leading garbage before the header within the first 1024 bytes.
MAGIC_SEARCH_WINDOW = 1024
# Browsers send application/pdf; some clients (curl -F) send application/octet-stream.
ACCEPTED_CONTENT_TYPES = frozenset(
    {"application/pdf", "application/x-pdf", "application/octet-stream"}
)
_READ_CHUNK = 1024 * 1024
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class InspectedUpload:
    sha256: str
    size_bytes: int


def sanitize_filename(raw: str | None) -> str:
    """Display-safe filename: no directories, no control characters, bounded length."""
    name = PurePosixPath((raw or "").replace("\\", "/")).name
    name = _CONTROL_CHARS.sub("", unicodedata.normalize("NFC", name)).strip()
    return name[-255:] or "documento.pdf"


def default_title(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0]
    return re.sub(r"[_\s]+", " ", stem).strip()[:300] or "Documento sin título"


def inspect_pdf_upload(
    file: BinaryIO, *, filename: str | None, content_type: str | None, max_bytes: int
) -> InspectedUpload:
    """Validate the upload and compute its SHA-256 (the idempotency key) in one pass."""
    if not filename or not filename.lower().endswith(".pdf"):
        raise UnsupportedMediaTypeError(
            ErrorCode.UNSUPPORTED_MEDIA_TYPE, "Solo se admiten archivos PDF (.pdf)."
        )
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared and declared not in ACCEPTED_CONTENT_TYPES:
        raise UnsupportedMediaTypeError(
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            f"Tipo de contenido no admitido ({declared}). Sube un PDF.",
        )

    file.seek(0)
    head = file.read(MAGIC_SEARCH_WINDOW)
    if not head:
        raise AppError(ErrorCode.EMPTY_FILE, "El archivo está vacío.")
    if PDF_MAGIC not in head:
        raise UnsupportedMediaTypeError(
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "El contenido no es un PDF válido aunque la extensión lo sea.",
        )

    digest = hashlib.sha256(head)
    size = len(head)
    while chunk := file.read(_READ_CHUNK):
        size += len(chunk)
        if size > max_bytes:
            raise PayloadTooLargeError(
                ErrorCode.FILE_TOO_LARGE,
                f"El archivo supera el límite de {max_bytes // (1024 * 1024)} MB.",
            )
        digest.update(chunk)
    if size > max_bytes:  # small files read entirely in the first chunk
        raise PayloadTooLargeError(
            ErrorCode.FILE_TOO_LARGE,
            f"El archivo supera el límite de {max_bytes // (1024 * 1024)} MB.",
        )

    file.seek(0)
    return InspectedUpload(sha256=digest.hexdigest(), size_bytes=size)
