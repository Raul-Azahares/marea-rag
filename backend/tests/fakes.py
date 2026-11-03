"""Test doubles shared across test modules."""

import uuid
from collections.abc import Sequence

from app.providers.base import EmbeddingBatch, EmbeddingProvider, ProviderError


class RecordingQueue:
    """In-memory TaskQueue: records what would have been published to the broker."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []
        self.available = True

    def enqueue_ingestion(self, document_id: uuid.UUID) -> bool:
        if not self.available:
            return False
        self.enqueued.append(document_id)
        return True


class FlakyEmbedder:
    """Raises `error` on the first `failures` calls, then delegates to a real embedder."""

    def __init__(self, inner: EmbeddingProvider, *, failures: int, error: ProviderError) -> None:
        self.model_name = inner.model_name
        self.dimensions = inner.dimensions
        self._inner = inner
        self._failures = failures
        self._error = error
        self.calls = 0

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        self.calls += 1
        if self.calls <= self._failures:
            raise self._error
        return self._inner.embed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self._inner.embed_query(text)
