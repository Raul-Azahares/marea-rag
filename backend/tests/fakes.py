"""Test doubles shared across test modules."""

import json
import uuid
from collections.abc import Callable, Sequence

from pydantic import BaseModel

from app.providers.base import (
    ChatMessage,
    ChatModel,
    ChatResult,
    EmbeddingBatch,
    EmbeddingProvider,
    ProviderError,
)
from app.rag.prompt import parse_fragments


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


# A scripted step: raw output, an exception to raise, or a function of the prompt's fragments.
Step = str | Exception | Callable[[dict[str, str]], str]


class ScriptedChatModel:
    """Plays `steps` in order, then delegates to `then` (if given). Records every call."""

    model_name = "scripted"

    def __init__(self, steps: Sequence[Step], then: ChatModel | None = None) -> None:
        self._steps = list(steps)
        self._then = then
        self.calls: list[list[ChatMessage]] = []

    async def complete(
        self, messages: Sequence[ChatMessage], *, response_schema: type[BaseModel]
    ) -> ChatResult:
        self.calls.append(list(messages))
        if not self._steps:
            if self._then is None:
                raise AssertionError("ScriptedChatModel ran out of steps")
            return await self._then.complete(messages, response_schema=response_schema)
        step = self._steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            prompt = next(m.content for m in messages if m.role == "user")
            step = step(parse_fragments(prompt))
        return ChatResult(content=step, model=self.model_name, input_tokens=10, output_tokens=5)


def answer_json(*statements: tuple[str, str, str], status: str = "answered") -> str:
    """Build an LLM answer from (text, fragment_id, quote) triples."""
    return json.dumps(
        {
            "status": status,
            "statements": [
                {"text": text, "citations": [{"fragment_id": fid, "quote": quote}]}
                for text, fid, quote in statements
            ],
        },
        ensure_ascii=False,
    )


class EmbedderDown:
    """Embedding provider whose query path is unavailable."""

    def __init__(self, inner: EmbeddingProvider, error: ProviderError) -> None:
        self.model_name = inner.model_name
        self.dimensions = inner.dimensions
        self._inner = inner
        self._error = error

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        return self._inner.embed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        raise self._error
