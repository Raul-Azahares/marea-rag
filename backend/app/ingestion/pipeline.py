"""Ingestion of one document: extract -> chunk -> embed -> index.

A message can be delivered more than once (acks_late), so a run must be safe to repeat:

* **Mutual exclusion.** A PostgreSQL advisory lock keyed by the document id is held for the
  whole run, on its own connection. A duplicate delivery finds it taken and does nothing.
  If the worker dies, its connection closes and PostgreSQL releases the lock: no time-based
  heuristics.
* **No stray reprocessing.** READY and FAILED documents are never reprocessed by a stray
  message. FAILED ones come back only through the API, which resets them to PENDING.
* **Atomic writes.** Chunks are computed in memory and written in ONE transaction that also
  flips the status to READY, so a document is never half-indexed. Chunk ids are
  deterministic, so a re-run writes identical rows.
* **Poison-message guard.** `attempts` is incremented and committed *before* any work. If
  a PDF kills the process (OOM, parser crash), the redelivered message still counts. Past
  `ingest_max_attempts` the document is failed instead of crash-looping forever.

Celery-agnostic on purpose: tests call `run_ingestion` directly.
"""

import time
import uuid
from dataclasses import dataclass
from enum import StrEnum

from opentelemetry import trace
from sqlalchemy import Connection, Engine, delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ErrorCode
from app.core.logging import get_logger
from app.core.telemetry import current_trace_id
from app.db.models import EMBEDDING_DIMENSIONS, Chunk, Document, DocumentStatus, IngestionStage
from app.ingestion.chunking import ChunkDraft, chunk_document
from app.ingestion.errors import IngestionError, TransientIngestionError
from app.ingestion.injection import SUSPECTED_INJECTION, chunk_flags
from app.ingestion.pdf_extraction import extract_pages
from app.providers.base import EmbeddingProvider, ProviderError
from app.storage import FileStorage

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class Outcome(StrEnum):
    READY = "ready"
    FAILED = "failed"
    SKIPPED_LOCKED = "skipped_locked"  # another worker holds the document right now
    SKIPPED_DONE = "skipped_done"  # already READY/FAILED: a duplicate message
    SKIPPED_MISSING = "skipped_missing"  # unknown document id


@dataclass(frozen=True)
class IngestionResult:
    outcome: Outcome
    document_id: uuid.UUID
    chunk_count: int = 0
    page_count: int = 0
    error_code: str | None = None


@dataclass(frozen=True)
class IngestionDeps:
    engine: Engine
    storage: FileStorage
    embedder: EmbeddingProvider
    settings: Settings


@dataclass(frozen=True)
class _Claim:
    title: str
    attempt: int


def document_lock_key(document_id: uuid.UUID) -> int:
    # Documents use the first half of the UUID and lineages the second half (see _finalize).
    # A first version has lineage_id == id, and its two locks must never collide.
    return int.from_bytes(document_id.bytes[:8], "big", signed=True)


def lineage_lock_key(lineage_id: uuid.UUID) -> int:
    return int.from_bytes(lineage_id.bytes[8:], "big", signed=True)


def chunk_id(document_id: uuid.UUID, index: int) -> uuid.UUID:
    return uuid.uuid5(document_id, f"chunk-{index}")


HEADER_SEPARATOR = " \u203a "  # single right-pointing angle quotation mark


def context_header(title: str, draft: ChunkDraft) -> str:
    return HEADER_SEPARATOR.join((title, *draft.heading_path))[:600]


# ---------------------------------------------------------------------------- entry
def run_ingestion(document_id: uuid.UUID, deps: IngestionDeps) -> IngestionResult:
    trace.get_current_span().set_attribute("marea.document.id", str(document_id))
    key = document_lock_key(document_id)
    with deps.engine.connect() as lock_connection:
        acquired = bool(lock_connection.scalar(select(func.pg_try_advisory_lock(key))))
        lock_connection.commit()  # end the implicit transaction; a session-level lock survives
        if not acquired:
            logger.info("ingestion_skipped", document_id=str(document_id), reason="locked")
            return IngestionResult(Outcome.SKIPPED_LOCKED, document_id)
        try:
            return _ingest_locked(document_id, deps)
        finally:
            _release_lock(lock_connection, key)


def _release_lock(connection: Connection, key: int) -> None:
    try:
        connection.scalar(select(func.pg_advisory_unlock(key)))
        connection.commit()
    except Exception:
        # Could not unlock (database gone?): discard the connection; closing it releases
        # the lock server-side instead of returning a locked connection to the pool.
        connection.invalidate()


def _ingest_locked(document_id: uuid.UUID, deps: IngestionDeps) -> IngestionResult:
    claim = _claim(document_id, deps)
    if isinstance(claim, IngestionResult):
        return claim
    settings = deps.settings
    started = time.perf_counter()
    try:
        with tracer.start_as_current_span("ingest.extract") as span:
            extracted = extract_pages(
                _read_file(document_id, deps.storage), max_pages=settings.max_pdf_pages
            )
            span.set_attribute("marea.document.page_count", extracted.page_count)
        _set_progress(deps, document_id, IngestionStage.CHUNKING, 20, extracted.page_count)

        with tracer.start_as_current_span("ingest.chunk") as span:
            drafts = chunk_document(
                extracted.pages,
                chunk_size=settings.chunk_size,
                overlap=settings.chunk_overlap,
                min_size=settings.chunk_min_size,
            )
            span.set_attribute("marea.ingest.chunk_count", len(drafts))
        if not drafts:
            raise IngestionError(ErrorCode.PDF_NO_TEXT, "El PDF no contiene texto aprovechable.")
        _set_progress(deps, document_id, IngestionStage.EMBEDDING, 30)

        headers = [context_header(claim.title, draft) for draft in drafts]
        vectors = _embed(document_id, drafts, headers, deps)

        _set_progress(deps, document_id, IngestionStage.INDEXING, 95)
        with tracer.start_as_current_span("ingest.persist"):
            suspicious = _finalize(
                document_id, drafts, headers, vectors, extracted.page_count, deps
            )
    except IngestionError as exc:
        mark_failed(deps.engine, document_id, exc.code, exc.message)
        return IngestionResult(Outcome.FAILED, document_id, error_code=exc.code)

    logger.info(
        "ingestion_completed",
        document_id=str(document_id),
        attempt=claim.attempt,
        page_count=extracted.page_count,
        chunk_count=len(drafts),
        suspicious_chunks=suspicious,
        embedding_model=deps.embedder.model_name,
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
    return IngestionResult(
        Outcome.READY, document_id, chunk_count=len(drafts), page_count=extracted.page_count
    )


# --------------------------------------------------------------------------- steps
def _claim(document_id: uuid.UUID, deps: IngestionDeps) -> _Claim | IngestionResult:
    with Session(deps.engine) as session, session.begin():
        document = session.get(Document, document_id)
        if document is None:
            logger.warning("ingestion_skipped", document_id=str(document_id), reason="missing")
            return IngestionResult(Outcome.SKIPPED_MISSING, document_id)
        if document.status in (DocumentStatus.READY, DocumentStatus.FAILED):
            logger.info(
                "ingestion_skipped", document_id=str(document_id), reason=document.status.value
            )
            return IngestionResult(
                Outcome.SKIPPED_DONE, document_id, error_code=document.error_code
            )

        document.attempts += 1
        trace.get_current_span().set_attribute("marea.ingest.attempt", document.attempts)
        if document.attempts > deps.settings.ingest_max_attempts:
            _apply_failure(
                document,
                ErrorCode.MAX_ATTEMPTS_EXCEEDED,
                f"Se abandonó tras {deps.settings.ingest_max_attempts} intentos fallidos.",
            )
            logger.error("poison_document_failed", document_id=str(document_id))
            return IngestionResult(
                Outcome.FAILED, document_id, error_code=ErrorCode.MAX_ATTEMPTS_EXCEEDED
            )

        document.status = DocumentStatus.PROCESSING
        document.stage = IngestionStage.EXTRACTING
        document.progress = 5
        document.error_code = None
        document.error_message = None
        document.ingest_trace_id = current_trace_id()
        logger.info("ingestion_started", document_id=str(document_id), attempt=document.attempts)
        return _Claim(title=document.title, attempt=document.attempts)


def _read_file(document_id: uuid.UUID, storage: FileStorage) -> bytes:
    try:
        return storage.read_bytes(document_id)
    except FileNotFoundError as exc:
        raise IngestionError(
            ErrorCode.FILE_MISSING, "El archivo original no está en el almacenamiento."
        ) from exc


def _set_progress(
    deps: IngestionDeps,
    document_id: uuid.UUID,
    stage: IngestionStage,
    progress: int,
    page_count: int | None = None,
) -> None:
    values: dict[str, object] = {"stage": stage.value, "progress": progress}
    if page_count is not None:
        values["page_count"] = page_count
    with Session(deps.engine) as session, session.begin():
        session.execute(update(Document).where(Document.id == document_id).values(**values))


def _embed(
    document_id: uuid.UUID, drafts: list[ChunkDraft], headers: list[str], deps: IngestionDeps
) -> list[list[float]]:
    # The header (document title + clause) is embedded with the text but never displayed:
    # a clause like "Quedan excluidos..." becomes findable under its subject.
    texts = [f"{header}\n{draft.content}" for header, draft in zip(headers, drafts, strict=True)]
    size = deps.settings.embedding_batch_size
    batches = [texts[i : i + size] for i in range(0, len(texts), size)]
    vectors: list[list[float]] = []
    tokens = 0
    with tracer.start_as_current_span("ingest.embed") as span:
        span.set_attribute("gen_ai.operation.name", "embeddings")
        span.set_attribute("gen_ai.request.model", deps.embedder.model_name)
        span.set_attribute("marea.embedding.batch_count", len(batches))
        for number, batch in enumerate(batches, start=1):
            try:
                result = deps.embedder.embed_documents(batch)
            except ProviderError as exc:
                if exc.retryable:
                    raise TransientIngestionError(ErrorCode.PROVIDER_UNAVAILABLE, str(exc)) from exc
                raise IngestionError(
                    ErrorCode.PROVIDER_REJECTED,
                    "El proveedor de embeddings rechazó la petición (revisa el modelo).",
                ) from exc
            if len(result.vectors) != len(batch) or any(
                len(vector) != EMBEDDING_DIMENSIONS for vector in result.vectors
            ):
                raise IngestionError(
                    ErrorCode.PROVIDER_REJECTED, "El proveedor devolvió embeddings inesperados."
                )
            vectors.extend(result.vectors)
            tokens += result.input_tokens or 0
            _set_progress(
                deps, document_id, IngestionStage.EMBEDDING, 30 + 60 * number // len(batches)
            )
        span.set_attribute("gen_ai.usage.input_tokens", tokens)
    return vectors


def _finalize(
    document_id: uuid.UUID,
    drafts: list[ChunkDraft],
    headers: list[str],
    vectors: list[list[float]],
    page_count: int,
    deps: IngestionDeps,
) -> int:
    """Swap in the chunks and mark READY in one transaction. Returns the suspicious-chunk count."""
    model = deps.embedder.model_name
    suspicious = 0
    with Session(deps.engine) as session, session.begin():
        document = session.get_one(Document, document_id)
        # Serialise version switches within a lineage, so two versions finishing at the same
        # time cannot both end up "current".
        session.execute(select(func.pg_advisory_xact_lock(lineage_lock_key(document.lineage_id))))
        session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        for draft, header, vector in zip(drafts, headers, vectors, strict=True):
            flags = chunk_flags(draft.content)
            suspicious += SUSPECTED_INJECTION in flags
            session.add(
                Chunk(
                    id=chunk_id(document_id, draft.index),
                    document_id=document_id,
                    chunk_index=draft.index,
                    content=draft.content,
                    section=draft.section,
                    context_header=header,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    char_count=len(draft.content),
                    embedding=vector,
                    embedding_model=model,
                    flags=flags,
                )
            )
        document.status = DocumentStatus.READY
        document.stage = None
        document.progress = 100
        document.page_count = page_count
        document.chunk_count = len(drafts)
        document.embedding_model = model
        document.error_code = None
        document.error_message = None
        document.processed_at = func.now()
        _switch_current_version(session, document)
    if suspicious:
        logger.warning("suspicious_chunks_detected", document_id=str(document_id), count=suspicious)
    return suspicious


def _switch_current_version(session: Session, document: Document) -> None:
    newer = session.scalar(
        select(Document.id)
        .where(
            Document.lineage_id == document.lineage_id,
            Document.status == DocumentStatus.READY,
            Document.version > document.version,
        )
        .order_by(Document.version.desc())
        .limit(1)
    )
    if newer is not None:  # finished after a newer version: born superseded
        document.superseded_at = func.now()
        document.superseded_by_id = newer
        return
    session.execute(
        update(Document)
        .where(
            Document.lineage_id == document.lineage_id,
            Document.id != document.id,
            Document.status == DocumentStatus.READY,
            Document.superseded_at.is_(None),
            Document.version < document.version,
        )
        .values(superseded_at=func.now(), superseded_by_id=document.id)
    )


# ------------------------------------------------------------- state transitions
def _apply_failure(document: Document, code: ErrorCode, message: str) -> None:
    document.status = DocumentStatus.FAILED
    document.stage = None
    document.progress = 0
    document.error_code = code
    document.error_message = message[:500]
    document.processed_at = func.now()


def mark_failed(engine: Engine, document_id: uuid.UUID, code: ErrorCode, message: str) -> None:
    with Session(engine) as session, session.begin():
        document = session.get(Document, document_id)
        if document is None or document.status is DocumentStatus.READY:
            return
        _apply_failure(document, code, message)
    logger.warning("ingestion_failed", document_id=str(document_id), error_code=code)


def note_retry(engine: Engine, document_id: uuid.UUID, message: str) -> None:
    """Show the user why a document is still processing (a retry is scheduled)."""
    with Session(engine) as session, session.begin():
        session.execute(
            update(Document)
            .where(Document.id == document_id, Document.status == DocumentStatus.PROCESSING)
            .values(error_message=message[:500])
        )
