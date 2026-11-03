"""The ingestion pipeline against a real PostgreSQL + pgvector (no Celery involved)."""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ErrorCode
from app.db.models import Document, DocumentStatus
from app.db.session import get_sync_engine
from app.ingestion.errors import TransientIngestionError
from app.ingestion.injection import SUSPECTED_INJECTION
from app.ingestion.pipeline import (
    IngestionDeps,
    Outcome,
    chunk_id,
    document_lock_key,
    run_ingestion,
)
from app.providers.base import EmbeddingProvider, ProviderRejectedError, ProviderUnavailableError
from app.providers.fake import HashingEmbeddingProvider
from tests.conftest import sample_pdf
from tests.fakes import FlakyEmbedder
from tests.integration.ingestion_helpers import add_document, chunks_of, load, storage
from tests.pdf_factory import make_encrypted_pdf

pytestmark = pytest.mark.integration

HOGAR_2025 = "marea-hogar-condicionado-2025.pdf"
HOGAR_2026 = "marea-hogar-condicionado-2026.pdf"


@pytest.fixture
def deps(clean_database: None) -> IngestionDeps:
    return make_deps(HashingEmbeddingProvider(768))


def make_deps(embedder: EmbeddingProvider) -> IngestionDeps:
    return IngestionDeps(
        engine=get_sync_engine(), storage=storage(), embedder=embedder, settings=get_settings()
    )


def test_sample_policy_is_indexed(deps: IngestionDeps) -> None:
    document_id = add_document(sample_pdf(HOGAR_2025), title="Marea Hogar Plus 2025")

    result = run_ingestion(document_id, deps)

    document = load(document_id)
    chunks = chunks_of(document_id)
    assert result.outcome is Outcome.READY
    assert (document.status, document.stage, document.progress) == (DocumentStatus.READY, None, 100)
    assert document.page_count == 6
    assert document.chunk_count == len(chunks) > 10
    assert document.attempts == 1
    assert document.embedding_model == "fake-hashing-v1"
    assert document.processed_at is not None
    assert all(len(c.embedding) == 768 for c in chunks)
    assert all(c.context_header.startswith("Marea Hogar Plus 2025") for c in chunks)
    assert all(1 <= c.page_start <= c.page_end <= 6 for c in chunks)
    assert [c.id for c in chunks] == [chunk_id(document_id, c.chunk_index) for c in chunks]


def test_indexed_chunks_are_searchable_by_vector_and_full_text(deps: IngestionDeps) -> None:
    document_id = add_document(sample_pdf(HOGAR_2025))
    run_ingestion(document_id, deps)
    question = HashingEmbeddingProvider(768).embed("daños por agua en la segunda vivienda")

    with Session(get_sync_engine()) as session:
        nearest = session.execute(
            text("SELECT section FROM chunks ORDER BY embedding <=> CAST(:q AS vector) LIMIT 1"),
            {"q": str(question)},
        ).scalar_one()
        fts_hits = session.execute(
            text("SELECT count(*) FROM chunks WHERE tsv @@ plainto_tsquery('es_unaccent', :q)"),
            {"q": "segunda vivienda deshabitada"},  # accents and plurals do not matter
        ).scalar_one()

    assert nearest == "Artículo 4. Daños por agua"
    assert fts_hits >= 1


def test_duplicate_message_is_a_no_op(deps: IngestionDeps) -> None:
    document_id = add_document(sample_pdf(HOGAR_2025))
    run_ingestion(document_id, deps)
    first_ids = [c.id for c in chunks_of(document_id)]

    again = run_ingestion(document_id, deps)

    assert again.outcome is Outcome.SKIPPED_DONE
    assert [c.id for c in chunks_of(document_id)] == first_ids
    assert load(document_id).attempts == 1


def test_reprocessing_rewrites_identical_chunks(deps: IngestionDeps) -> None:
    document_id = add_document(sample_pdf(HOGAR_2025))
    run_ingestion(document_id, deps)
    before = [(c.id, c.content) for c in chunks_of(document_id)]
    with Session(get_sync_engine()) as session, session.begin():
        session.execute(update(Document).where(Document.id == document_id).values(status="pending"))

    assert run_ingestion(document_id, deps).outcome is Outcome.READY
    assert [(c.id, c.content) for c in chunks_of(document_id)] == before  # no duplicates


@pytest.mark.parametrize(
    ("factory", "code"),
    [
        (lambda blank: b"%PDF-1.7\ncorrupted body", ErrorCode.PDF_CORRUPT),
        (lambda blank: blank(), ErrorCode.PDF_NO_TEXT),
        (
            lambda blank: make_encrypted_pdf("Artículo 1. Texto", user_password="x"),
            ErrorCode.PDF_ENCRYPTED,
        ),
    ],
)
def test_permanent_failures_are_not_retried(
    deps: IngestionDeps,
    make_blank_pdf: Callable[[], bytes],
    factory: Callable[[Callable[[], bytes]], bytes],
    code: ErrorCode,
) -> None:
    document_id = add_document(factory(make_blank_pdf))

    result = run_ingestion(document_id, deps)

    document = load(document_id)
    assert result.outcome is Outcome.FAILED
    assert (document.status, document.error_code, document.attempts) == (
        DocumentStatus.FAILED,
        code,
        1,
    )
    assert document.error_message
    assert chunks_of(document_id) == []


def test_missing_file_fails_permanently(deps: IngestionDeps) -> None:
    document_id = add_document(b"%PDF-1.7", store_file=False)

    assert run_ingestion(document_id, deps).error_code == ErrorCode.FILE_MISSING


def test_transient_provider_error_is_raised_for_retry_then_recovers(clean_database: None) -> None:
    flaky = FlakyEmbedder(
        HashingEmbeddingProvider(768), failures=1, error=ProviderUnavailableError("503")
    )
    deps = make_deps(flaky)
    document_id = add_document(sample_pdf(HOGAR_2025))

    with pytest.raises(TransientIngestionError):
        run_ingestion(document_id, deps)
    assert load(document_id).status is DocumentStatus.PROCESSING  # left for the retry

    assert run_ingestion(document_id, deps).outcome is Outcome.READY
    assert load(document_id).attempts == 2


def test_rejected_provider_request_fails_permanently(clean_database: None) -> None:
    rejecting = FlakyEmbedder(
        HashingEmbeddingProvider(768), failures=99, error=ProviderRejectedError("404 model")
    )
    document_id = add_document(sample_pdf(HOGAR_2025))

    result = run_ingestion(document_id, make_deps(rejecting))

    assert result.error_code == ErrorCode.PROVIDER_REJECTED
    assert rejecting.calls == 1  # no point retrying a configuration error


def test_poison_guard_fails_a_document_that_keeps_crashing(deps: IngestionDeps) -> None:
    # Simulates a PDF that killed the worker on every previous attempt.
    max_attempts = get_settings().ingest_max_attempts
    document_id = add_document(b"irrelevant", attempts=max_attempts, store_file=False)

    result = run_ingestion(document_id, deps)

    document = load(document_id)
    assert result.outcome is Outcome.FAILED
    assert document.error_code == ErrorCode.MAX_ATTEMPTS_EXCEEDED
    assert document.attempts == max_attempts + 1


def test_concurrent_delivery_is_skipped_while_another_worker_holds_the_lock(
    deps: IngestionDeps,
) -> None:
    document_id = add_document(sample_pdf(HOGAR_2025))
    with get_sync_engine().connect() as other_worker:
        other_worker.scalar(select(func.pg_advisory_lock(document_lock_key(document_id))))
        other_worker.commit()

        result = run_ingestion(document_id, deps)

        other_worker.scalar(select(func.pg_advisory_unlock(document_lock_key(document_id))))
        other_worker.commit()

    assert result.outcome is Outcome.SKIPPED_LOCKED
    assert (load(document_id).status, load(document_id).attempts) == (DocumentStatus.PENDING, 0)


def test_new_version_replaces_the_previous_one_once_ready(deps: IngestionDeps) -> None:
    v1 = add_document(sample_pdf(HOGAR_2025))
    run_ingestion(v1, deps)
    v2 = add_document(sample_pdf(HOGAR_2026), lineage_id=v1, version=2)

    assert load(v1).superseded_at is None  # v2 still pending: v1 keeps serving queries
    run_ingestion(v2, deps)

    assert load(v1).superseded_by_id == v2
    assert load(v2).superseded_at is None
    assert len(chunks_of(v1)) > 0  # kept: past citations stay verifiable


def test_version_finishing_after_a_newer_one_is_born_superseded(deps: IngestionDeps) -> None:
    lineage = uuid.uuid4()
    v2 = add_document(sample_pdf(HOGAR_2025), lineage_id=lineage, version=2)
    v3 = add_document(sample_pdf(HOGAR_2026), lineage_id=lineage, version=3)

    run_ingestion(v3, deps)
    run_ingestion(v2, deps)  # finishes late

    assert load(v2).superseded_by_id == v3
    assert load(v3).superseded_at is None


def test_injection_attempt_is_flagged_on_its_chunk(deps: IngestionDeps) -> None:
    document_id = add_document(sample_pdf("adversarial/anexo-condiciones-especiales.pdf"))

    run_ingestion(document_id, deps)

    flagged = [c.section for c in chunks_of(document_id) if SUSPECTED_INJECTION in c.flags]
    assert flagged == ["Artículo 2. Nota para el asistente virtual"]
