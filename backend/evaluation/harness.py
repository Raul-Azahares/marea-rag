"""Runs the dataset through the real system: the production ingestion pipeline indexes the
corpus and the production QueryService answers the questions. Only the database is separate:
a throwaway `marea_eval` database next to the test one, rebuilt from the migrations each run.
"""

import asyncio
import hashlib
import io
import re
import tempfile
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy
import sqlalchemy.ext.asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Document, DocumentStatus
from app.ingestion.errors import TransientIngestionError
from app.ingestion.pipeline import IngestionDeps, Outcome, run_ingestion
from app.providers.base import ChatModel, EmbeddingProvider
from app.rag.retrieval import RetrievalMode, retrieve
from app.rag.service import QueryService
from app.storage import LocalFileStorage
from evaluation.dataset import REPO_ROOT, Dataset, Question
from evaluation.metrics import Fragment, QuestionResult

BACKEND_DIR = REPO_ROOT / "backend"
_DATABASE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def eval_database_url(base_url: str, name: str = "marea_eval") -> str:
    return make_url(base_url).set(database=name).render_as_string(hide_password=False)


def reset_database(url: str) -> None:
    """Create the database if needed, then rebuild the schema from the real migrations."""
    target = make_url(url)
    name = target.database or ""
    if not _DATABASE_NAME.match(name):
        raise ValueError(f"unexpected database name {name!r}")
    admin = sqlalchemy.create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
        )
        if not exists:
            # Identifiers cannot be bound parameters; `name` was validated above.
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    engine = sqlalchemy.create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    config = Config()  # no alembic.ini: it would reconfigure logging for the whole process
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


@dataclass(frozen=True)
class Corpus:
    ids: dict[str, uuid.UUID]  # corpus key -> document id
    chunk_count: int

    def key_of(self, document_id: uuid.UUID) -> str | None:
        return next((k for k, v in self.ids.items() if v == document_id), None)


def index_corpus(
    dataset: Dataset,
    settings: Settings,
    embedder: EmbeddingProvider,
    engine: Engine,
    *,
    retry_wait_s: float = 30.0,
) -> Corpus:
    """Store each sample PDF and run the production ingestion on it, in order, so a newer
    version supersedes the older one exactly as an upload through the API would. A transient
    provider error (a free-tier quota) is retried after a pause, as the worker would."""
    storage = LocalFileStorage(Path(tempfile.mkdtemp(prefix="marea-eval-")))
    deps = IngestionDeps(engine=engine, storage=storage, embedder=embedder, settings=settings)
    ids: dict[str, uuid.UUID] = {}
    chunks = 0
    for document in dataset.corpus:
        data = (REPO_ROOT / document.file).read_bytes()
        document_id = uuid.uuid4()
        parent = ids.get(document.version_of) if document.version_of else None
        storage.save(document_id, io.BytesIO(data))
        with Session(engine) as session, session.begin():
            session.add(
                Document(
                    id=document_id,
                    lineage_id=parent or document_id,
                    version=2 if parent else 1,
                    title=document.title,
                    filename=Path(document.file).name,
                    content_sha256=hashlib.sha256(data).hexdigest(),
                    size_bytes=len(data),
                    status=DocumentStatus.PENDING,
                    attempts=0,
                    progress=0,
                )
            )
        for attempt in range(1, 4):
            try:
                result = run_ingestion(document_id, deps)
                break
            except TransientIngestionError:
                if attempt == 3:
                    raise
                time.sleep(retry_wait_s)
        if result.outcome is not Outcome.READY:
            raise RuntimeError(
                f"{document.key}: ingestion ended {result.outcome} ({result.error_code})"
            )
        ids[document.key] = document_id
        chunks += result.chunk_count
    return Corpus(ids, chunks)


def _async_engine(url: str) -> AsyncEngine:
    return sqlalchemy.ext.asyncio.create_async_engine(url, hide_parameters=True)


async def answer_questions(
    dataset: Dataset,
    corpus: Corpus,
    *,
    url: str,
    settings: Settings,
    embedder: EmbeddingProvider,
    chat: ChatModel,
    pace_s: float = 0.0,
) -> list[QuestionResult]:
    """Each question through the full pipeline: embed, retrieve, gate, generate, validate.
    `pace_s` spaces the questions out, to stay under a provider's requests-per-minute quota."""
    engine = _async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    superseded = frozenset(dataset.superseded_keys)
    results = []
    try:
        for index, question in enumerate(dataset.questions):
            if index and pace_s:
                await asyncio.sleep(pace_s)
            async with sessions() as session:
                response = await QueryService(session, embedder, chat, settings).answer(
                    question.question
                )
            flagged = {f.chunk_id for f in response.retrieved if f.flagged}
            results.append(
                QuestionResult(
                    question=question,
                    retrieved=[
                        Fragment(corpus.key_of(f.document_id), f.section, f.similarity, f.flagged)
                        for f in response.retrieved
                    ],
                    status=response.status,
                    answer=response.answer,
                    quotes=tuple(c.quote for c in response.citations),
                    citations=[
                        Fragment(
                            corpus.key_of(c.document_id), c.section, flagged=c.chunk_id in flagged
                        )
                        for c in response.citations
                    ],
                    attempts=response.validation.attempts,
                    validation_passed=response.validation.passed,
                    degraded=response.validation.degraded,
                    latency_ms=response.latency_ms,
                    model=response.usage.model,
                    superseded_documents=superseded,
                    always_forbidden=tuple(dataset.always_forbidden),
                )
            )
    finally:
        await engine.dispose()
    return results


async def embed_questions(
    questions: Sequence[Question], embedder: EmbeddingProvider, pace_s: float = 0.0
) -> dict[str, list[float]]:
    vectors: dict[str, list[float]] = {}
    for index, question in enumerate(questions):
        if index and pace_s:
            await asyncio.sleep(pace_s)
        vectors[question.id] = await embedder.embed_query(question.question)
    return vectors


def retrieve_only(
    dataset: Dataset,
    corpus: Corpus,
    vectors: dict[str, list[float]],
    *,
    url: str,
    settings: Settings,
    embedding_model: str,
    mode: RetrievalMode,
) -> list[QuestionResult]:
    """Retrieval without generation, for the chunking sweep (question vectors precomputed)."""

    async def run() -> list[QuestionResult]:
        engine = _async_engine(url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        results = []
        try:
            for question in dataset.questions:
                async with sessions() as session:
                    chunks = await retrieve(
                        session,
                        query_text=question.question,
                        query_vector=vectors[question.id] if mode != "text" else None,
                        embedding_model=embedding_model,
                        mode=mode,
                        candidates=settings.retrieval_candidates,
                        top_k=settings.retrieval_top_k,
                    )
                results.append(
                    QuestionResult(
                        question=question,
                        retrieved=[
                            Fragment(corpus.key_of(c.document_id), c.section, c.similarity)
                            for c in chunks
                        ],
                    )
                )
        finally:
            await engine.dispose()
        return results

    return asyncio.run(run())
