"""Application settings, read from environment variables (12-factor).

Defaults point at the throwaway test infrastructure (`make test-infra`, ports 55432/56379)
and at deterministic fake providers, so the test suite runs with zero configuration.
docker-compose overrides the connection URLs for the real stack.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # --- Runtime --------------------------------------------------------------
    environment: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"
    log_json: bool = True

    # --- Infrastructure ---------------------------------------------------------
    database_url: str = "postgresql+psycopg://marea:marea@localhost:55432/marea_test"
    redis_url: str = "redis://localhost:56379/0"

    # --- Uploads ------------------------------------------------------------------
    upload_dir: Path = Path("/data/uploads")
    max_upload_mb: int = Field(default=20, ge=1, le=200)
    max_pdf_pages: int = Field(default=300, ge=1)

    # --- Providers (fake = deterministic and offline; litellm = real provider) -----
    llm_provider: Literal["fake", "litellm"] = "fake"
    llm_model: str = "gemini/gemini-3-flash-preview"
    llm_fallback_models: list[str] = Field(default_factory=list)
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.0

    embedding_provider: Literal["fake", "litellm"] = "fake"
    embedding_model: str = "gemini/gemini-embedding-001"
    # Fixed by the database schema (vector(768)); checked against the provider at startup.
    embedding_dimensions: int = 768
    embedding_batch_size: int = Field(default=32, ge=1, le=100)
    embedding_timeout_s: float = 30.0

    # Read by LiteLLM straight from the environment; declared here so it is documented
    # and masked (SecretStr) if settings are ever printed.
    gemini_api_key: SecretStr | None = None

    # --- Chunking (characters) -----------------------------------------------------
    chunk_size: int = 900
    chunk_overlap: int = 150
    chunk_min_size: int = 200

    # --- Retrieval ---------------------------------------------------------------------
    retrieval_mode: Literal["hybrid", "vector"] = "hybrid"
    retrieval_candidates: int = 20  # per retriever, before fusion
    retrieval_top_k: int = 6  # fragments sent to the LLM
    # Evidence gate: below this cosine similarity nothing counts as evidence. It depends on
    # the embedding model and is calibrated on the evaluation set (see DECISIONS.md).
    retrieval_min_similarity: float = 0.12

    # --- Answer validation -----------------------------------------------------------------
    validation_max_retries: int = 1
    quote_min_score: float = 90.0  # rapidfuzz partial_ratio, 0-100

    # --- Ingestion worker ------------------------------------------------------------------
    ingest_soft_time_limit_s: int = 300
    ingest_time_limit_s: int = 360
    ingest_max_retries: int = 5  # transient errors (provider/DB), exponential backoff
    ingest_max_attempts: int = 6  # poison-message guard, counted in the DB
    reconcile_interval_s: int = 60
    stale_pending_after_s: int = 120

    # --- Observability ---------------------------------------------------------------------
    otel_enabled: bool = True
    # Opt-in only: never put policy text, questions or prompts into spans by default.
    otel_capture_content: bool = False
    jaeger_ui_url: str = "http://localhost:16686"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
