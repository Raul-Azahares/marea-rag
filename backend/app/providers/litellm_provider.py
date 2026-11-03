"""Real providers through LiteLLM: one interface for Gemini, OpenAI, Ollama, Bedrock...

The model is chosen by configuration (EMBEDDING_MODEL=gemini/gemini-embedding-001,
LLM_MODEL=...). Vendor exceptions are mapped onto our ProviderError hierarchy, so callers
only reason about retryable vs permanent failures.
"""

from collections.abc import Sequence
from typing import Any

import litellm
from litellm.exceptions import (
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    Timeout,
)
from pydantic import BaseModel

from app.providers.base import (
    ChatMessage,
    ChatResult,
    EmbeddingBatch,
    ProviderError,
    ProviderRateLimitError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


def map_provider_error(exc: Exception) -> ProviderError:
    """Classify a LiteLLM exception. The message is the exception type and status code only:
    provider error bodies can echo parts of the request."""
    status = getattr(exc, "status_code", None)
    message = f"{type(exc).__name__} (status={status})"
    if isinstance(exc, Timeout):
        return ProviderTimeoutError(message)
    if isinstance(exc, RateLimitError):
        return ProviderRateLimitError(message)
    if isinstance(
        exc, AuthenticationError | PermissionDeniedError | NotFoundError | BadRequestError
    ):
        return ProviderRejectedError(message)
    # ServiceUnavailable, InternalServerError, APIConnectionError and anything unexpected:
    # assume transient. The retry budget bounds the cost of being wrong.
    return ProviderUnavailableError(message)


def _vector(item: Any) -> list[float]:
    values = item["embedding"] if isinstance(item, dict) else item.embedding
    return [float(v) for v in values]


class LiteLLMEmbeddingProvider:
    def __init__(self, *, model: str, dimensions: int, timeout_s: float, max_retries: int) -> None:
        self.model_name = model
        self.dimensions = dimensions
        self._timeout_s = timeout_s
        self._max_retries = max_retries

    def _params(self, task_type: str) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "dimensions": self.dimensions,
            # Gemini embeds documents and queries asymmetrically (better retrieval).
            # Providers without the notion drop the parameter.
            "task_type": task_type,
            "drop_params": True,
            "timeout": self._timeout_s,
            "num_retries": self._max_retries,
        }

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        try:
            response = litellm.embedding(input=list(texts), **self._params("RETRIEVAL_DOCUMENT"))
        except Exception as exc:
            raise map_provider_error(exc) from exc
        vectors = [_vector(item) for item in response.data]
        usage = getattr(response, "usage", None)
        return EmbeddingBatch(vectors=vectors, input_tokens=getattr(usage, "prompt_tokens", None))

    async def embed_query(self, text: str) -> list[float]:
        try:
            response = await litellm.aembedding(input=[text], **self._params("RETRIEVAL_QUERY"))
        except Exception as exc:
            raise map_provider_error(exc) from exc
        return _vector(response.data[0])


class LiteLLMChatModel:
    def __init__(
        self,
        *,
        model: str,
        temperature: float,
        timeout_s: float,
        max_retries: int,
        fallbacks: Sequence[str] = (),
        reasoning_effort: str = "",
    ) -> None:
        self.model_name = model
        self._temperature = temperature
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._fallbacks = list(fallbacks)
        self._reasoning_effort = reasoning_effort

    async def complete(
        self, messages: Sequence[ChatMessage], *, response_schema: type[BaseModel]
    ) -> ChatResult:
        params: dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            # Structured output: the provider constrains generation to this JSON schema.
            "response_format": response_schema,
            "temperature": self._temperature,
            "timeout": self._timeout_s,
            "num_retries": self._max_retries,
            "drop_params": True,
        }
        if self._fallbacks:
            params["fallbacks"] = self._fallbacks
        if self._reasoning_effort:
            params["reasoning_effort"] = self._reasoning_effort
        try:
            response = await litellm.acompletion(**params)
        except Exception as exc:
            raise map_provider_error(exc) from exc
        usage = getattr(response, "usage", None)
        return ChatResult(
            content=response.choices[0].message.content or "",
            model=getattr(response, "model", None) or self.model_name,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
        )
