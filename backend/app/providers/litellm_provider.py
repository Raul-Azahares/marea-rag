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

from app.providers.base import (
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
