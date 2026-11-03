"""Question answering end to end through the HTTP API, with deterministic fake providers."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_chat_model, get_embedding_provider
from app.db.models import Chunk
from app.db.session import get_sync_engine
from app.main import create_app
from app.providers.base import (
    ChatModel,
    EmbeddingProvider,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.providers.fake import FakeChatModel, HashingEmbeddingProvider
from app.rag.service import LLM_UNAVAILABLE_ANSWER, NO_EVIDENCE_ANSWER
from app.text_utils import normalize_for_match
from tests.fakes import EmbedderDown, ScriptedChatModel, answer_json

pytestmark = pytest.mark.integration

QUESTION = "¿La póliza cubre daños por agua en segunda vivienda?"
INVENTED = "esta frase no aparece en ningún documento de la aseguradora"


@asynccontextmanager
async def api(
    *, chat: ChatModel | None = None, embedder: EmbeddingProvider | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    if chat is not None:
        app.dependency_overrides[get_chat_model] = lambda: chat
    if embedder is not None:
        app.dependency_overrides[get_embedding_provider] = lambda: embedder
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def ask(question: str, **kwargs: Any) -> dict[str, Any]:
    document_ids = kwargs.pop("document_ids", None)
    payload: dict[str, Any] = {"question": question}
    if document_ids:
        payload["document_ids"] = [str(d) for d in document_ids]
    async with api(**kwargs) as client:
        response = await client.post("/api/v1/query", json=payload)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def real_quote(fragment_text: str) -> str:
    return " ".join(fragment_text.split()[:8])


# ------------------------------------------------------------------ happy path
async def test_answer_is_grounded_in_the_current_version(corpus: dict[str, uuid.UUID]) -> None:
    body = await ask(QUESTION)

    assert body["status"] == "answered"
    assert body["no_evidence"] is False
    assert body["confidence"] in ("high", "medium")
    assert body["validation"] == {"passed": True, "attempts": 1, "degraded": False, "issues": []}
    assert body["citations"]
    assert {c["document_id"] for c in body["citations"]} == {str(corpus["hogar_v2"])}
    assert {c["section"] for c in body["citations"]} == {"Artículo 4. Daños por agua"}
    refs = {c["ref"] for c in body["citations"]}
    assert all(s["citation_refs"] and set(s["citation_refs"]) <= refs for s in body["statements"])
    assert "[1]" in body["answer"]
    cited = {f["chunk_id"] for f in body["retrieved"] if f["cited"]}
    assert {c["chunk_id"] for c in body["citations"]} <= cited
    assert body["usage"]["model"] == FakeChatModel.model_name


async def test_every_quote_can_be_checked_in_its_source_fragment(
    corpus: dict[str, uuid.UUID],
) -> None:
    body = await ask(QUESTION)

    async with api() as client:
        for citation in body["citations"]:
            fragment = (await client.get(f"/api/v1/chunks/{citation['chunk_id']}")).json()
            assert normalize_for_match(citation["quote"]) in normalize_for_match(
                fragment["content"]
            )


async def test_figures_come_from_the_new_version_only(corpus: dict[str, uuid.UUID]) -> None:
    body = await ask("¿Qué franquicia se aplica a los daños por agua en la segunda vivienda?")

    assert "250 euros" in body["answer"]  # 2026 edition
    assert "300 euros" not in body["answer"]  # superseded 2025 figure


# ------------------------------------------------------------ refusing to answer
async def test_unrelated_question_is_refused_without_calling_the_llm(
    corpus: dict[str, uuid.UUID],
) -> None:
    must_not_be_called = ScriptedChatModel([])

    body = await ask("¿Cuál es la capital de Francia?", chat=must_not_be_called)

    assert must_not_be_called.calls == []
    assert body["status"] == "insufficient_evidence"
    assert body["no_evidence"] is True
    assert body["confidence"] == "none"
    assert body["citations"] == []
    assert body["validation"]["attempts"] == 0
    assert body["answer"] == NO_EVIDENCE_ANSWER


async def test_question_outside_the_selected_documents_is_not_answered_from_others(
    corpus: dict[str, uuid.UUID],
) -> None:
    body = await ask(
        "¿La asistencia en viaje funciona desde el kilómetro 0?",
        document_ids=[corpus["hogar_v2"]],
    )

    assert str(corpus["auto"]) not in {c["document_id"] for c in body["citations"]}
    assert {f["document_id"] for f in body["retrieved"]} <= {str(corpus["hogar_v2"])}


# ----------------------------------------------- validation: repair, degrade, reject
async def test_invented_fragment_is_fixed_by_the_repair_attempt(
    corpus: dict[str, uuid.UUID],
) -> None:
    chat = ScriptedChatModel(
        [answer_json(("Está cubierto.", "F9", "se extiende a la segunda vivienda únicamente"))],
        then=FakeChatModel(),
    )

    body = await ask(QUESTION, chat=chat)

    assert body["status"] == "answered"
    assert body["validation"]["passed"] is True
    assert body["validation"]["attempts"] == 2
    assert body["confidence"] == "medium"  # needed a repair
    repair_prompt = chat.calls[1][-1].content
    assert "F9" in repair_prompt
    assert "no superó la validación" in repair_prompt


async def test_invalid_json_is_fixed_by_the_repair_attempt(corpus: dict[str, uuid.UUID]) -> None:
    body = await ask(QUESTION, chat=ScriptedChatModel(["esto no es JSON"], then=FakeChatModel()))

    assert body["status"] == "answered"
    assert body["validation"]["attempts"] == 2


async def test_unverifiable_claims_are_dropped_and_the_answer_degraded(
    corpus: dict[str, uuid.UUID],
) -> None:
    def half_invented(fragments: dict[str, str]) -> str:
        return answer_json(
            ("Afirmación respaldada.", "F1", real_quote(fragments["F1"])),
            ("Afirmación inventada.", "F1", INVENTED),
        )

    body = await ask(QUESTION, chat=ScriptedChatModel([half_invented, half_invented]))

    assert body["status"] == "partial"
    assert [s["text"] for s in body["statements"]] == ["Afirmación respaldada."]
    assert body["validation"]["passed"] is False
    assert body["validation"]["degraded"] is True
    assert body["validation"]["issues"][0]["code"] == "quote_not_found"
    assert body["confidence"] == "low"
    assert any("Se omitieron afirmaciones" in w for w in body["warnings"])


async def test_answer_with_nothing_verifiable_is_rejected(corpus: dict[str, uuid.UUID]) -> None:
    invented = answer_json(("Todo está cubierto.", "F1", INVENTED))

    body = await ask(QUESTION, chat=ScriptedChatModel([invented, invented]))

    assert body["status"] == "insufficient_evidence"
    assert body["no_evidence"] is True
    assert body["citations"] == []
    assert body["validation"]["degraded"] is True
    assert body["retrieved"]  # the agent can still review the fragments
    assert any("no produjo una respuesta verificable" in w for w in body["warnings"])


# ------------------------------------------------------------ provider failures
async def test_llm_outage_returns_the_relevant_fragments(corpus: dict[str, uuid.UUID]) -> None:
    body = await ask(QUESTION, chat=ScriptedChatModel([ProviderTimeoutError("timeout")]))

    assert body["status"] == "llm_unavailable"
    assert body["no_evidence"] is False
    assert body["answer"] == LLM_UNAVAILABLE_ANSWER
    assert body["retrieved"]
    assert body["confidence"] == "none"


async def test_embedding_outage_degrades_to_full_text_search(
    corpus: dict[str, uuid.UUID],
) -> None:
    down = EmbedderDown(HashingEmbeddingProvider(768), ProviderUnavailableError("503"))

    body = await ask(QUESTION, embedder=down)

    assert body["status"] == "answered"
    assert all(f["similarity"] is None for f in body["retrieved"])
    assert any("solo la búsqueda por texto" in w for w in body["warnings"])


# ------------------------------------------------------------------- security
async def test_injected_instructions_are_flagged_and_not_followed(
    corpus: dict[str, uuid.UUID],
) -> None:
    body = await ask(
        "¿Cubre el seguro los daños causados por perros y gatos?",
        document_ids=[corpus["annex"]],
    )

    assert any(f["flagged"] for f in body["retrieved"])
    assert any("posible inyección" in w for w in body["warnings"])
    assert "sin franquicia" not in body["answer"]  # the injected claim is not repeated


# ------------------------------------------------------------- fragment viewer
async def test_superseded_fragments_stay_readable_for_past_citations(
    corpus: dict[str, uuid.UUID],
) -> None:
    with Session(get_sync_engine()) as session:
        old_chunk = session.scalars(
            select(Chunk.id).where(Chunk.document_id == corpus["hogar_v1"]).limit(1)
        ).one()

    async with api() as client:
        found = await client.get(f"/api/v1/chunks/{old_chunk}")
        missing = await client.get(f"/api/v1/chunks/{uuid.uuid4()}")

    assert found.status_code == 200
    assert found.json()["document_superseded"] is True
    assert found.json()["document_version"] == 1
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CHUNK_NOT_FOUND"


@pytest.mark.parametrize("question", ["  a ", "x" * 1001])
async def test_question_is_validated(corpus: dict[str, uuid.UUID], question: str) -> None:
    async with api() as client:
        response = await client.post("/api/v1/query", json={"question": question})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
