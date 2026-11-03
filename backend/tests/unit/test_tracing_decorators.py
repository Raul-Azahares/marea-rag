import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from app.providers.base import ChatMessage, ProviderTimeoutError
from app.providers.fake import FakeChatModel, HashingEmbeddingProvider
from app.providers.tracing import TracedChatModel, TracedEmbeddingProvider, provider_name
from app.rag.models import LLMAnswer
from tests.fakes import ScriptedChatModel

PROMPT = [ChatMessage("system", "s"), ChatMessage("user", "<pregunta>\nhola\n</pregunta>")]


async def test_chat_calls_get_a_genai_client_span(spans: InMemorySpanExporter) -> None:
    model = TracedChatModel(FakeChatModel(), provider="fake", temperature=0.0)

    await model.complete(PROMPT, response_schema=LLMAnswer)

    (span,) = spans.get_finished_spans()
    assert span.name == "chat fake-extractive-v1"
    assert span.kind is SpanKind.CLIENT
    attributes = dict(span.attributes or {})
    assert attributes["gen_ai.operation.name"] == "chat"
    assert attributes["gen_ai.provider.name"] == "fake"
    assert attributes["gen_ai.request.model"] == "fake-extractive-v1"
    assert attributes["gen_ai.response.model"] == "fake-extractive-v1"
    assert int(attributes["gen_ai.usage.input_tokens"]) > 0  # type: ignore[arg-type]
    assert int(attributes["gen_ai.usage.output_tokens"]) > 0  # type: ignore[arg-type]


async def test_failed_model_call_is_marked_as_an_error(spans: InMemorySpanExporter) -> None:
    model = TracedChatModel(
        ScriptedChatModel([ProviderTimeoutError("timeout")]), provider="gcp.gemini", temperature=0
    )

    with pytest.raises(ProviderTimeoutError):
        await model.complete(PROMPT, response_schema=LLMAnswer)

    (span,) = spans.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert (span.attributes or {})["error.type"] == "ProviderTimeoutError"


def test_embedding_batches_get_a_span_with_tokens(spans: InMemorySpanExporter) -> None:
    embedder = TracedEmbeddingProvider(HashingEmbeddingProvider(768), provider="fake")

    embedder.embed_documents(["uno", "dos"])

    (span,) = spans.get_finished_spans()
    attributes = dict(span.attributes or {})
    assert span.name == "embeddings fake-hashing-v1"
    assert attributes["gen_ai.operation.name"] == "embeddings"
    assert attributes["gen_ai.embeddings.dimension.count"] == 768
    assert attributes["marea.embedding.batch_size"] == 2
    assert int(attributes["gen_ai.usage.input_tokens"]) > 0  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gemini/gemini-3-flash-preview", "gcp.gemini"),
        ("openai/gpt-5", "openai"),
        ("ollama/llama3", "ollama"),
        ("custom/model", "custom"),
    ],
)
def test_provider_names_follow_the_semantic_conventions(model: str, expected: str) -> None:
    assert provider_name(model) == expected
