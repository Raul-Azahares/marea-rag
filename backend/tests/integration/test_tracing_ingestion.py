"""One trace from the upload request to the background task and its model calls, with useful
attributes, and with no policy text or question anywhere in spans or logs."""

import logging
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from app.db.models import DocumentStatus
from app.main import create_app
from tests.integration.ingestion_helpers import load, wait_for
from tests.pdf_factory import make_text_pdf
from tests.span_helpers import all_recorded_text, in_trace, named, wait_for_span

pytestmark = pytest.mark.integration

INGEST_RUN = "run/marea.ingest_document"


@pytest_asyncio.fixture
async def live_client(clean_database: None, worker: None) -> AsyncIterator[httpx.AsyncClient]:
    """API wired to the real broker, consumed by the in-process Celery worker."""
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def upload(client: httpx.AsyncClient, data: bytes) -> httpx.Response:
    return await client.post(
        "/api/v1/documents", files={"file": ("poliza.pdf", data, "application/pdf")}
    )


POLICY_PAGES = [
    "Artículo 1. Objeto del seguro\nLa Aseguradora cubre los daños materiales de la vivienda.",
    "Artículo 2. Daños por agua\nSe cubren los escapes accidentales de agua de las tuberías.",
]


async def test_upload_trace_follows_the_document_into_the_worker_and_model_calls(
    live_client: httpx.AsyncClient, spans: InMemorySpanExporter
) -> None:
    response = await upload(live_client, make_text_pdf(POLICY_PAGES))
    document_id = response.json()["id"]
    wait_for(uuid.UUID(document_id), DocumentStatus.READY)
    run = wait_for_span(spans, INGEST_RUN)

    trace = in_trace(spans, run.context.trace_id)
    names = {s.name for s in trace}
    trace_hex = format(run.context.trace_id, "032x")
    # API request -> Celery publish -> Celery task -> domain steps -> model calls: one trace.
    assert {
        "POST /api/v1/documents",
        "apply_async/marea.ingest_document",
        INGEST_RUN,
        "ingest.extract",
        "ingest.chunk",
        "ingest.embed",
        "ingest.persist",
        "embeddings fake-hashing-v1",
    } <= names
    assert named(trace, "apply_async/marea.ingest_document").kind is SpanKind.PRODUCER
    assert run.kind is SpanKind.CONSUMER
    assert (run.attributes or {})["marea.document.id"] == document_id
    assert (run.attributes or {})["marea.ingest.attempt"] == 1
    assert (named(trace, "ingest.extract").attributes or {})["marea.document.page_count"] == 2
    assert int((named(trace, "ingest.chunk").attributes or {})["marea.ingest.chunk_count"]) > 0  # type: ignore[arg-type]
    embedding = named(trace, "embeddings fake-hashing-v1")
    assert embedding.kind is SpanKind.CLIENT
    assert (embedding.attributes or {})["gen_ai.operation.name"] == "embeddings"
    # Database statements are traced on both sides (SQL text only, never bound values).
    services_with_sql = {
        s.resource.attributes["service.name"]
        for s in trace
        if (s.attributes or {}).get("db.system") == "postgresql"
    }
    assert services_with_sql  # API inserts the row; the worker writes chunks
    # The client gets the trace id, and the document remembers its ingestion trace.
    assert response.headers["x-trace-id"] == trace_hex
    assert load(uuid.UUID(document_id)).ingest_trace_id == trace_hex


SECRET_CLAUSE = "ZAFIRO7731"
SECRET_QUESTION = "CENTINELA4402"


async def test_no_policy_text_or_question_reaches_spans_or_logs(
    live_client: httpx.AsyncClient,
    spans: InMemorySpanExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    pdf = make_text_pdf(
        [
            "Artículo 1. Cobertura especial\n"
            f"La cláusula {SECRET_CLAUSE} cubre los daños por caída de meteoritos en la vivienda."
        ]
    )

    document_id = (await upload(live_client, pdf)).json()["id"]
    wait_for(uuid.UUID(document_id), DocumentStatus.READY)
    wait_for_span(spans, INGEST_RUN)
    answer = await live_client.post(
        "/api/v1/query",
        json={"question": f"¿Qué cubre la cláusula de meteoritos? {SECRET_QUESTION}"},
    )

    recorded = all_recorded_text(spans.get_finished_spans())
    logs = caplog.text
    # Positive controls: the telemetry was actually captured...
    assert "ingestion_completed" in logs
    assert document_id in logs
    assert "POST /api/v1/query" in recorded
    assert SECRET_CLAUSE in answer.text  # ...and the content is where it belongs: the answer.
    # ...but neither the document text nor the question is in spans or logs.
    for secret in (SECRET_CLAUSE, SECRET_QUESTION, "meteoritos"):
        assert secret not in recorded
        assert secret not in logs
