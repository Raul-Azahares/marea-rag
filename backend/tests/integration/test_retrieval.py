"""Hybrid retrieval against real pgvector + PostgreSQL full-text search."""

import uuid

import pytest

from app.db.session import get_async_sessionmaker
from app.providers.fake import HashingEmbeddingProvider
from app.rag.models import RetrievedChunk
from app.rag.retrieval import RetrievalMode, retrieve

pytestmark = pytest.mark.integration

EMBEDDER = HashingEmbeddingProvider(768)


async def search(
    query: str,
    *,
    mode: RetrievalMode = "hybrid",
    with_vector: bool = True,
    document_ids: list[uuid.UUID] | None = None,
    model: str = EMBEDDER.model_name,
) -> list[RetrievedChunk]:
    async with get_async_sessionmaker()() as session:
        return await retrieve(
            session,
            query_text=query,
            query_vector=EMBEDDER.embed(query) if with_vector else None,
            embedding_model=model,
            mode=mode,
            candidates=20,
            top_k=6,
            document_ids=document_ids,
        )


async def test_hybrid_search_finds_the_clause_in_the_current_version(
    corpus: dict[str, uuid.UUID],
) -> None:
    results = await search("daños por agua en la segunda vivienda")

    top = results[0]
    assert top.section == "Artículo 4. Daños por agua"
    assert top.document_id == corpus["hogar_v2"]
    assert top.similarity is not None  # found by both retrievers
    assert top.text_rank is not None
    assert corpus["hogar_v1"] not in {r.document_id for r in results}  # superseded: never searched


async def test_text_only_mode_works_without_embeddings(corpus: dict[str, uuid.UUID]) -> None:
    results = await search("asistencia en viaje desde el kilómetro", mode="text", with_vector=False)

    assert results
    assert results[0].document_id == corpus["auto"]
    assert all(r.similarity is None for r in results)
    assert all(r.text_rank is not None and r.text_rank > 0 for r in results)


async def test_vector_only_mode_ignores_full_text(corpus: dict[str, uuid.UUID]) -> None:
    results = await search("robo del vehículo", mode="vector")

    assert results
    assert all(r.text_rank is None for r in results)


async def test_results_can_be_restricted_to_some_documents(corpus: dict[str, uuid.UUID]) -> None:
    results = await search("franquicia por siniestro", document_ids=[corpus["auto"]])

    assert results
    assert {r.document_id for r in results} == {corpus["auto"]}


async def test_vectors_from_another_embedding_model_are_never_compared(
    corpus: dict[str, uuid.UUID],
) -> None:
    assert await search("daños por agua", model="another-embedding-model") == []


async def test_results_are_ranked_by_fused_score(corpus: dict[str, uuid.UUID]) -> None:
    results = await search("plazo para comunicar el siniestro")

    assert 0 < len(results) <= 6
    assert [r.score for r in results] == sorted((r.score for r in results), reverse=True)
