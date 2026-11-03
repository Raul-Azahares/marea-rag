"""Builds the configured providers (LLM_PROVIDER / EMBEDDING_PROVIDER)."""

from app.core.config import Settings
from app.db.models import EMBEDDING_DIMENSIONS
from app.providers.base import ChatModel, EmbeddingProvider
from app.providers.fake import FakeChatModel, HashingEmbeddingProvider
from app.providers.litellm_provider import LiteLLMChatModel, LiteLLMEmbeddingProvider


class ProviderConfigurationError(RuntimeError):
    pass


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    # Fail fast on a mismatch with the vector(768) column instead of on the first INSERT.
    if settings.embedding_dimensions != EMBEDDING_DIMENSIONS:
        raise ProviderConfigurationError(
            f"EMBEDDING_DIMENSIONS={settings.embedding_dimensions}, but the database column is "
            f"vector({EMBEDDING_DIMENSIONS}). Changing it requires a migration and re-indexing."
        )
    if settings.embedding_provider == "fake":
        return HashingEmbeddingProvider(settings.embedding_dimensions)
    return LiteLLMEmbeddingProvider(
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        timeout_s=settings.embedding_timeout_s,
        # One quick retry for blips; longer outages are handled by Celery's backoff.
        max_retries=1,
    )


def build_chat_model(settings: Settings) -> ChatModel:
    if settings.llm_provider == "fake":
        return FakeChatModel()
    return LiteLLMChatModel(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        timeout_s=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,
        fallbacks=settings.llm_fallback_models,
        reasoning_effort=settings.llm_reasoning_effort,
    )
