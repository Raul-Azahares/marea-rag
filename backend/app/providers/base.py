"""Provider-agnostic interfaces. The rest of the code depends on these, never on LiteLLM
or on a specific vendor, so providers can be swapped by configuration."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    """A model-provider call failed. `retryable` says whether trying again may help."""

    retryable = False


class ProviderTimeoutError(ProviderError):
    retryable = True


class ProviderRateLimitError(ProviderError):
    retryable = True


class ProviderUnavailableError(ProviderError):
    retryable = True


class ProviderRejectedError(ProviderError):
    """Authentication, unknown or retired model, malformed request: retrying won't help."""


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    input_tokens: int | None


class EmbeddingProvider(Protocol):
    model_name: str  # stored on every chunk; retrieval only compares vectors of one model
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        """Embed passages for indexing (sync: used by the Celery worker)."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a user question for retrieval (async: used by the API)."""
        ...
