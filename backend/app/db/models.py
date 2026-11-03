"""Relational model: documents (one row per uploaded file version) and their chunks."""

import uuid
from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIMENSIONS = 768  # must match the migration; checked against the provider at startup
TEXT_SEARCH_CONFIG = "es_unaccent"  # Spanish stemming + accent-insensitive (see migration)


class Base(DeclarativeBase):
    # Deterministic constraint names: readable errors and clean Alembic migrations.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class IngestionStage(StrEnum):
    """Finer-grained progress shown while a document is `processing`."""

    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"


class Document(Base):
    """One uploaded file. Versions of the same logical document share `lineage_id`.

    A new version only replaces the previous one (sets its `superseded_at`) once it is
    READY, so queries keep working while it is being ingested. Superseded versions keep
    their chunks: citations given in past answers stay verifiable.
    """

    __tablename__ = "documents"
    # Fetch server-generated values (created_at, updated_at) with RETURNING on INSERT *and*
    # UPDATE. Otherwise they are expired after a flush and re-read lazily, which is implicit
    # I/O that AsyncSession forbids (MissingGreenlet).
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lineage_id: Mapped[uuid.UUID] = mapped_column(index=True)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(255))
    # Idempotency key: the same bytes are never ingested twice.
    content_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[DocumentStatus] = mapped_column(
        Enum(
            DocumentStatus,
            name="document_status",
            native_enum=False,  # VARCHAR + CHECK: adding a status needs no type migration
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        default=DocumentStatus.PENDING,
        index=True,
    )
    stage: Mapped[str | None] = mapped_column(String(20))
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(500))
    # Incremented *before* each processing attempt: the poison-message guard (a PDF that
    # kills the worker process never gets to increment Celery's own retry counter).
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    chunk_count: Mapped[int | None] = mapped_column(Integer)
    embedding_model: Mapped[str | None] = mapped_column(String(120))
    ingest_trace_id: Mapped[str | None] = mapped_column(String(32))

    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("lineage_id", "version", name="uq_documents_lineage_version"),
    )

    @property
    def superseded(self) -> bool:
        return self.superseded_at is not None


class Chunk(Base):
    """A retrievable fragment of a document, with its embedding and full-text vector."""

    __tablename__ = "chunks"

    # Deterministic uuid5(document_id, chunk_index): re-ingesting yields the same ids.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)  # exactly what is shown and quoted
    section: Mapped[str | None] = mapped_column(String(300))  # e.g. "Artículo 5. Daños por agua"
    # Document title + section: embedded and indexed with the content, never displayed.
    context_header: Mapped[str] = mapped_column(String(600))
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    char_count: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    # Vectors from different models are not comparable: retrieval filters on this.
    embedding_model: Mapped[str] = mapped_column(String(120))
    flags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            f"to_tsvector('{TEXT_SEARCH_CONFIG}'::regconfig, context_header || ' ' || content)",
            persisted=True,
        ),
    )

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )
