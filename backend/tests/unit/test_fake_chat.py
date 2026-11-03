import json
import uuid

from app.providers.fake import FakeChatModel
from app.rag.models import LLMAnswer, RetrievedChunk
from app.rag.prompt import build_messages
from app.rag.validation import validate_answer


def chunk(content: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Marea Hogar Plus",
        document_version=1,
        content=content,
        section=None,
        page_start=1,
        page_end=1,
        flags=[],
        similarity=0.5,
        text_rank=None,
        score=0.03,
    )


FRAGMENTS = {
    "F1": chunk(
        "Se cubre el robo con fuerza en las cosas. El hurto, es decir, la sustracción sin "
        "fuerza ni violencia, no está cubierto por esta póliza."
    ),
    "F2": chunk(
        "La garantía de daños por agua se extiende a la segunda vivienda únicamente cuando "
        "figure contratada la modalidad Segunda Residencia."
    ),
}


async def ask(question: str) -> str:
    result = await FakeChatModel().complete(
        build_messages(question, FRAGMENTS), response_schema=LLMAnswer
    )
    return result.content


async def test_answers_by_quoting_the_most_relevant_sentence() -> None:
    raw = await ask("¿Cubre la póliza daños por agua en la segunda vivienda?")

    answer = json.loads(raw)
    assert answer["status"] == "answered"
    assert answer["statements"][0]["citations"][0]["fragment_id"] == "F2"
    # The real validator accepts what the fake produces: it exercises the full pipeline.
    assert validate_answer(raw, FRAGMENTS, min_quote_score=90).passed


async def test_declares_insufficient_evidence_when_nothing_overlaps() -> None:
    answer = json.loads(await ask("¿Cuál es la capital de Francia?"))
    assert answer == {"status": "insufficient_evidence", "statements": []}


async def test_is_deterministic() -> None:
    question = "¿Está cubierto el hurto sin fuerza?"
    assert await ask(question) == await ask(question)
