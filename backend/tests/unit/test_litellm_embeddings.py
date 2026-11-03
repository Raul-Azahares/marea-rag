from types import SimpleNamespace
from typing import Any

import pytest
from litellm import exceptions as litellm_errors

from app.providers import litellm_provider
from app.providers.base import ProviderRateLimitError
from app.providers.litellm_provider import LiteLLMEmbeddingProvider


def fake_response(count: int) -> SimpleNamespace:
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1 * (i + 1)] * 4) for i in range(count)],
        usage=SimpleNamespace(prompt_tokens=42),
    )


@pytest.fixture
def provider() -> LiteLLMEmbeddingProvider:
    return LiteLLMEmbeddingProvider(
        model="gemini/gemini-embedding-001", dimensions=4, timeout_s=5, max_retries=1
    )


def test_documents_are_embedded_as_retrieval_documents(
    provider: LiteLLMEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        litellm_provider.litellm, "embedding", lambda **kw: calls.append(kw) or fake_response(2)
    )

    batch = provider.embed_documents(["a", "b"])

    assert batch.vectors == [[0.1] * 4, [0.2] * 4]
    assert batch.input_tokens == 42
    assert calls[0]["input"] == ["a", "b"]
    assert calls[0]["task_type"] == "RETRIEVAL_DOCUMENT"
    assert (calls[0]["dimensions"], calls[0]["timeout"], calls[0]["num_retries"]) == (4, 5, 1)


async def test_queries_are_embedded_as_retrieval_queries(
    provider: LiteLLMEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_aembedding(**kw: Any) -> SimpleNamespace:
        calls.append(kw)
        return fake_response(1)

    monkeypatch.setattr(litellm_provider.litellm, "aembedding", fake_aembedding)

    assert await provider.embed_query("¿cubre el robo?") == [0.1] * 4
    assert calls[0]["task_type"] == "RETRIEVAL_QUERY"


def test_vendor_errors_surface_as_provider_errors(
    provider: LiteLLMEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    def rate_limited(**_: Any) -> None:
        raise litellm_errors.RateLimitError(message="slow down", llm_provider="gemini", model="m")

    monkeypatch.setattr(litellm_provider.litellm, "embedding", rate_limited)

    with pytest.raises(ProviderRateLimitError):
        provider.embed_documents(["a"])
