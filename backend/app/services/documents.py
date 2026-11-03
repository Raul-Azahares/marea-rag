"""Document use cases: upload (with deduplication and versioning), retry, read.

Ordering in `upload` is deliberate:
  1. validate + hash (nothing touched yet)
  2. store the file      -> a crash here leaves an orphan file, never a row without a file
  3. commit the row      -> the row in `pending` is the source of truth (an "outbox")
  4. enqueue the job     -> if the broker is down the row stays `pending` and the
                            reconciler enqueues it later; the upload still succeeds
"""

import uuid
from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import ConflictError, ErrorCode, NotFoundError
from app.core.logging import get_logger
from app.db.models import Document, DocumentStatus
from app.ingestion.upload_validation import default_title, inspect_pdf_upload, sanitize_filename
from app.storage import FileStorage
from app.task_queue import TaskQueue

logger = get_logger(__name__)


@dataclass(frozen=True)
class UploadResult:
    document: Document
    deduplicated: bool
    queued: bool


class DocumentService:
    def __init__(
        self,
        session: AsyncSession,
        storage: FileStorage,
        queue: TaskQueue,
        settings: Settings,
    ) -> None:
        self._session = session
        self._storage = storage
        self._queue = queue
        self._settings = settings

    # ------------------------------------------------------------------ commands
    async def upload(
        self,
        *,
        file: BinaryIO,
        filename: str | None,
        content_type: str | None,
        title: str | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> UploadResult:
        # Blocking file I/O and hashing run in a worker thread, off the event loop.
        inspected = await run_in_threadpool(
            inspect_pdf_upload,
            file,
            filename=filename,
            content_type=content_type,
            max_bytes=self._settings.max_upload_bytes,
        )
        existing = await self._find_by_hash(inspected.sha256)
        if existing is not None:
            return await self._on_duplicate(existing)

        safe_name = sanitize_filename(filename)
        document_id = uuid.uuid4()
        if parent_id is None:
            lineage_id, version, inherited_title = document_id, 1, None
        else:
            parent = await self.get(parent_id)
            lineage_id, inherited_title = parent.lineage_id, parent.title
            version = await self._next_version(lineage_id)

        document = Document(
            id=document_id,
            lineage_id=lineage_id,
            version=version,
            title=(title or "").strip() or inherited_title or default_title(safe_name),
            filename=safe_name,
            content_sha256=inspected.sha256,
            size_bytes=inspected.size_bytes,
            status=DocumentStatus.PENDING,
            progress=0,
            attempts=0,
        )
        await run_in_threadpool(self._storage.save, document_id, file)
        self._session.add(document)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            await run_in_threadpool(self._storage.delete, document_id)
            # Lost a race against an identical concurrent upload: that one wins.
            winner = await self._find_by_hash(inspected.sha256)
            if winner is not None:
                return await self._on_duplicate(winner)
            # Otherwise two new versions of the same lineage collided on the version number.
            raise ConflictError(
                ErrorCode.CONCURRENT_UPLOAD,
                "Se está subiendo otra versión de este documento a la vez. Inténtalo de nuevo.",
            ) from None
        except BaseException:
            await self._session.rollback()
            await run_in_threadpool(self._storage.delete, document_id)
            raise

        logger.info(
            "document_uploaded",
            document_id=str(document_id),
            lineage_id=str(lineage_id),
            version=version,
            size_bytes=inspected.size_bytes,
        )
        queued = await run_in_threadpool(self._queue.enqueue_ingestion, document_id)
        return UploadResult(document=document, deduplicated=False, queued=queued)

    async def retry(self, document_id: uuid.UUID) -> UploadResult:
        document = await self.get(document_id)
        if document.status is not DocumentStatus.FAILED:
            raise ConflictError(
                ErrorCode.INVALID_STATE,
                "Solo se pueden reintentar documentos fallidos "
                f"(estado actual: {document.status}).",
            )
        return await self._requeue(document, deduplicated=False)

    # ------------------------------------------------------------------- queries
    async def get(self, document_id: uuid.UUID) -> Document:
        document = await self._session.get(Document, document_id)
        if document is None:
            raise NotFoundError(ErrorCode.DOCUMENT_NOT_FOUND, "El documento no existe.")
        return document

    async def list(self, *, limit: int, offset: int) -> tuple[list[Document], int]:
        total = await self._session.scalar(select(func.count()).select_from(Document)) or 0
        rows = await self._session.scalars(
            select(Document)
            .order_by(Document.created_at.desc(), Document.version.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), total

    # ------------------------------------------------------------------- helpers
    async def _find_by_hash(self, sha256: str) -> Document | None:
        result: Document | None = await self._session.scalar(
            select(Document).where(Document.content_sha256 == sha256)
        )
        return result

    async def _next_version(self, lineage_id: uuid.UUID) -> int:
        current = await self._session.scalar(
            select(func.max(Document.version)).where(Document.lineage_id == lineage_id)
        )
        return (current or 0) + 1

    async def _on_duplicate(self, existing: Document) -> UploadResult:
        """The same bytes were uploaded before. Re-uploading a failed file retries it."""
        logger.info(
            "document_deduplicated",
            document_id=str(existing.id),
            status=existing.status.value,
        )
        if existing.status is DocumentStatus.FAILED:
            return await self._requeue(existing, deduplicated=True)
        return UploadResult(document=existing, deduplicated=True, queued=False)

    async def _requeue(self, document: Document, *, deduplicated: bool) -> UploadResult:
        # A human decided to try again: the poison-message counter starts over.
        document.status = DocumentStatus.PENDING
        document.stage = None
        document.progress = 0
        document.error_code = None
        document.error_message = None
        document.attempts = 0
        await self._session.commit()
        queued = await run_in_threadpool(self._queue.enqueue_ingestion, document.id)
        return UploadResult(document=document, deduplicated=deduplicated, queued=queued)
