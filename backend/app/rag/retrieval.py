"""Hybrid retrieval in a single SQL query: pgvector + PostgreSQL full-text search, fused
with Reciprocal Rank Fusion (RRF).

Why hybrid: policies hinge on exact terms ("franquicia", "segunda vivienda", article
numbers) that embeddings sometimes blur, while embeddings catch paraphrases the full-text
search misses. RRF fuses the two rankings by position only (1 / (k + rank)), so it needs no
calibration between cosine distances and text ranks. k = 60 is the usual value from the
original paper (Cormack et al., 2009).

Only current documents are searched: READY, not superseded, and embedded with the
configured model (vectors from different models are not comparable).
"""

import uuid
from collections.abc import Sequence
from typing import Literal

from pgvector.sqlalchemy import Vector
from sqlalchemy import Uuid, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EMBEDDING_DIMENSIONS
from app.rag.models import RetrievedChunk

RetrievalMode = Literal["hybrid", "vector", "text"]
RRF_K = 60

# Full-text query with OR semantics: plainto_tsquery ANDs every word, which a natural-language
# question would almost never satisfy. The expression is repeated where needed (not hoisted
# into a CTE) so the planner can use the GIN and HNSW indexes with plain parameters.
_TERMS = "replace(plainto_tsquery('es_unaccent', :query_text)::text, '&', '|')::tsquery"
_VECTOR = "CAST(:query_vector AS vector)"
_CURRENT = """
    d.status = 'ready' AND d.superseded_at IS NULL
    AND c.embedding_model = :embedding_model
    AND (CAST(:document_ids AS uuid[]) IS NULL
         OR c.document_id = ANY(CAST(:document_ids AS uuid[])))
"""

# Composed only from the constants above; every user-supplied value is a bound parameter.
_HYBRID_SQL = text(
    f"""
WITH vector_hits AS (
    SELECT id, row_number() OVER (ORDER BY distance) AS rank
    FROM (
        SELECT c.id, c.embedding <=> {_VECTOR} AS distance
        FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE :use_vector AND {_CURRENT}
        ORDER BY c.embedding <=> {_VECTOR}
        LIMIT :candidates
    ) nearest
),
text_hits AS (
    SELECT id, text_rank, row_number() OVER (ORDER BY text_rank DESC) AS rank
    FROM (
        SELECT c.id, ts_rank_cd(c.tsv, {_TERMS}) AS text_rank
        FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE :use_text AND c.tsv @@ {_TERMS} AND {_CURRENT}
        ORDER BY text_rank DESC
        LIMIT :candidates
    ) matched
),
fused AS (
    SELECT id,
           COALESCE(1.0 / (:rrf_k + v.rank), 0) + COALESCE(1.0 / (:rrf_k + t.rank), 0) AS score,
           t.text_rank
    FROM vector_hits v FULL OUTER JOIN text_hits t USING (id)
)
SELECT c.id, c.document_id, d.title, d.version, c.content, c.section,
       c.page_start, c.page_end, c.flags,
       CASE WHEN :use_vector THEN 1 - (c.embedding <=> {_VECTOR}) END AS similarity,
       f.text_rank, f.score
FROM fused f
JOIN chunks c ON c.id = f.id
JOIN documents d ON d.id = c.document_id
ORDER BY f.score DESC, similarity DESC NULLS LAST, c.id
LIMIT :top_k
"""  # noqa: S608
).bindparams(
    bindparam("query_vector", type_=Vector(EMBEDDING_DIMENSIONS)),
    bindparam("document_ids", type_=ARRAY(Uuid())),
)


async def retrieve(
    session: AsyncSession,
    *,
    query_text: str,
    query_vector: list[float] | None,
    embedding_model: str,
    mode: RetrievalMode,
    candidates: int,
    top_k: int,
    document_ids: Sequence[uuid.UUID] | None = None,
) -> list[RetrievedChunk]:
    use_vector = mode in ("hybrid", "vector") and query_vector is not None
    use_text = mode in ("hybrid", "text")
    # Filtered HNSW searches can return fewer rows than LIMIT; iterative scans (pgvector
    # >= 0.8) keep scanning until enough rows pass the filters.
    await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    rows = await session.execute(
        _HYBRID_SQL,
        {
            "query_vector": query_vector,
            "query_text": query_text,
            "embedding_model": embedding_model,
            "document_ids": list(document_ids) if document_ids else None,
            "use_vector": use_vector,
            "use_text": use_text,
            "candidates": candidates,
            "top_k": top_k,
            "rrf_k": RRF_K,
        },
    )
    return [
        RetrievedChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            document_title=row.title,
            document_version=row.version,
            content=row.content,
            section=row.section,
            page_start=row.page_start,
            page_end=row.page_end,
            flags=list(row.flags or []),
            similarity=float(row.similarity) if row.similarity is not None else None,
            text_rank=float(row.text_rank) if row.text_rank is not None else None,
            score=float(row.score),
        )
        for row in rows
    ]
