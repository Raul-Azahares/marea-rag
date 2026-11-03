"""Initial schema: documents, chunks, pgvector and Spanish full-text search.

Revision ID: 0001
Revises:
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    # Spanish stemming that also ignores accents, so "póliza" and "poliza" match.
    op.execute("CREATE TEXT SEARCH CONFIGURATION es_unaccent (COPY = pg_catalog.spanish)")
    op.execute(
        "ALTER TEXT SEARCH CONFIGURATION es_unaccent "
        "ALTER MAPPING FOR hword, hword_part, word WITH unaccent, spanish_stem"
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lineage_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "ready",
                "failed",
                name="document_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("stage", sa.String(20), nullable=True),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("embedding_model", sa.String(120), nullable=True),
        sa.Column("ingest_trace_id", sa.String(32), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint("content_sha256", name="uq_documents_content_sha256"),
        sa.UniqueConstraint("lineage_id", "version", name="uq_documents_lineage_version"),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["documents.id"],
            name="fk_documents_superseded_by_id_documents",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_documents_lineage_id", "documents", ["lineage_id"])
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("section", sa.String(300), nullable=True),
        sa.Column("context_header", sa.String(600), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column(
            "flags",
            postgresql.ARRAY(sa.String(40)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('es_unaccent'::regconfig, context_header || ' ' || content)",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    # Approximate nearest-neighbour index for cosine distance (the `<=>` operator).
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("documents")
    op.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS es_unaccent")
