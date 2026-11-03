"""The query trace: retrieval, generation and validation, with GenAI attributes."""

import uuid

import httpx
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from app.main import create_app
from tests.span_helpers import in_trace, named

pytestmark = pytest.mark.integration


async def test_query_trace_shows_each_step_and_the_model_usage(
    corpus: dict[str, uuid.UUID], spans: InMemorySpanExporter
) -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/query",
            json={"question": "¿La póliza cubre daños por agua en segunda vivienda?"},
        )

    body = response.json()
    trace = in_trace(spans, int(body["trace_id"], 16))
    server = named(trace, "POST /api/v1/query")
    retrieve = named(trace, "rag.retrieve")
    chat = named(trace, "chat fake-extractive-v1")
    validate = named(trace, "rag.validate")

    assert response.headers["x-trace-id"] == body["trace_id"]
    assert named(trace, "embeddings fake-hashing-v1").kind is SpanKind.CLIENT
    assert {"rag.generate"} <= {s.name for s in trace}
    # Retrieval: how much was found and how close the evidence was.
    assert (retrieve.attributes or {})["marea.rag.retrieval_mode"] == "hybrid"
    assert int((retrieve.attributes or {})["marea.rag.retrieved_count"]) > 0  # type: ignore[arg-type]
    assert float((retrieve.attributes or {})["marea.rag.best_similarity"]) > 0  # type: ignore[arg-type]
    # Generation: GenAI semantic conventions, with token usage.
    chat_attributes = dict(chat.attributes or {})
    assert chat.kind is SpanKind.CLIENT
    assert chat_attributes["gen_ai.operation.name"] == "chat"
    assert int(chat_attributes["gen_ai.usage.input_tokens"]) > 0  # type: ignore[arg-type]
    assert int(chat_attributes["gen_ai.usage.output_tokens"]) > 0  # type: ignore[arg-type]
    # Validation and outcome.
    assert (validate.attributes or {})["marea.rag.validation_passed"] is True
    assert (server.attributes or {})["marea.rag.status"] == "answered"
    assert int((server.attributes or {})["marea.rag.citation_count"]) >= 1  # type: ignore[arg-type]
    assert "marea.rag.question_length" in (server.attributes or {})
