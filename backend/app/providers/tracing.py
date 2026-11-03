"""A GenAI client span around every model call, following the OpenTelemetry GenAI semantic
conventions: span name "{operation} {model}", kind CLIENT, gen_ai.* attributes.

Applied as decorators by the factory: providers stay unaware of tracing, and every call is
covered whoever the caller is. Prompts and completions are deliberately not recorded; only
model names, token counts and outcomes are.
"""

from collections.abc import Sequence

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind
from pydantic import BaseModel

from app.providers.base import (
    ChatMessage,
    ChatModel,
    ChatResult,
    EmbeddingBatch,
    EmbeddingProvider,
    ProviderError,
)

tracer = trace.get_tracer(__name__)

_KNOWN_PROVIDERS = {
    "gemini": "gcp.gemini",
    "vertex_ai": "gcp.vertex_ai",
    "openai": "openai",
    "anthropic": "anthropic",
    "bedrock": "aws.bedrock",
    "ollama": "ollama",
}


def provider_name(model: str) -> str:
    """LiteLLM model ids are prefixed by provider ("gemini/..."); map that to semconv names."""
    prefix = model.split("/", 1)[0] if "/" in model else model
    return _KNOWN_PROVIDERS.get(prefix, prefix)


def _mark_error(span: Span, exc: ProviderError) -> None:
    span.set_attribute("error.type", type(exc).__name__)


class TracedChatModel:
    def __init__(self, inner: ChatModel, *, provider: str, temperature: float) -> None:
        self.model_name = inner.model_name
        self._inner = inner
        self._provider = provider
        self._temperature = temperature

    async def complete(
        self, messages: Sequence[ChatMessage], *, response_schema: type[BaseModel]
    ) -> ChatResult:
        with tracer.start_as_current_span(f"chat {self.model_name}", kind=SpanKind.CLIENT) as span:
            span.set_attributes(
                {
                    "gen_ai.operation.name": "chat",
                    "gen_ai.provider.name": self._provider,
                    "gen_ai.request.model": self.model_name,
                    "gen_ai.request.temperature": self._temperature,
                    "gen_ai.output.type": "json",
                }
            )
            try:
                result = await self._inner.complete(messages, response_schema=response_schema)
            except ProviderError as exc:
                _mark_error(span, exc)
                raise
            span.set_attribute("gen_ai.response.model", result.model)
            if result.input_tokens is not None:
                span.set_attribute("gen_ai.usage.input_tokens", result.input_tokens)
            if result.output_tokens is not None:
                span.set_attribute("gen_ai.usage.output_tokens", result.output_tokens)
            return result


class TracedEmbeddingProvider:
    def __init__(self, inner: EmbeddingProvider, *, provider: str) -> None:
        self.model_name = inner.model_name
        self.dimensions = inner.dimensions
        self._inner = inner
        self._provider = provider

    def _describe(self, span: Span) -> None:
        span.set_attributes(
            {
                "gen_ai.operation.name": "embeddings",
                "gen_ai.provider.name": self._provider,
                "gen_ai.request.model": self.model_name,
                "gen_ai.embeddings.dimension.count": self.dimensions,
            }
        )

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        name = f"embeddings {self.model_name}"
        with tracer.start_as_current_span(name, kind=SpanKind.CLIENT) as span:
            self._describe(span)
            span.set_attribute("marea.embedding.batch_size", len(texts))
            try:
                batch = self._inner.embed_documents(texts)
            except ProviderError as exc:
                _mark_error(span, exc)
                raise
            if batch.input_tokens is not None:
                span.set_attribute("gen_ai.usage.input_tokens", batch.input_tokens)
            return batch

    async def embed_query(self, text: str) -> list[float]:
        name = f"embeddings {self.model_name}"
        with tracer.start_as_current_span(name, kind=SpanKind.CLIENT) as span:
            self._describe(span)
            try:
                return await self._inner.embed_query(text)
            except ProviderError as exc:
                _mark_error(span, exc)
                raise
