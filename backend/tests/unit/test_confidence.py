import uuid

import pytest

from app.rag.confidence import Confidence, compute_confidence
from app.rag.models import LLMStatus, RetrievedChunk
from app.rag.validation import VerifiedCitation, VerifiedStatement

CHUNK = RetrievedChunk(
    chunk_id=uuid.uuid4(),
    document_id=uuid.uuid4(),
    document_title="T",
    document_version=1,
    content="c",
    section=None,
    page_start=1,
    page_end=1,
    flags=[],
    similarity=0.5,
    text_rank=None,
    score=0.03,
)


def statements(*, exact: bool = True) -> list[VerifiedStatement]:
    return [VerifiedStatement("x", (VerifiedCitation("F1", CHUNK, "q", exact=exact),))]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"statements": []}, "none"),
        ({}, "high"),
        ({"attempts": 2}, "medium"),  # needed a repair
        ({"exact": False}, "medium"),  # approximate quote
        ({"best_similarity": 0.2}, "medium"),  # weak evidence
        ({"degraded": True}, "low"),
        ({"status": "partial"}, "low"),
        ({"status": "conflicting_evidence"}, "low"),
    ],
)
def test_confidence_levels(kwargs: dict[str, object], expected: Confidence) -> None:
    exact = bool(kwargs.pop("exact", True))
    status: LLMStatus = kwargs.pop("status", "answered")  # type: ignore[assignment]
    result = compute_confidence(
        kwargs.pop("statements", statements(exact=exact)),  # type: ignore[arg-type]
        status=status,
        attempts=int(kwargs.pop("attempts", 1)),  # type: ignore[call-overload]
        degraded=bool(kwargs.pop("degraded", False)),
        best_similarity=kwargs.pop("best_similarity", 0.6),  # type: ignore[arg-type]
        high_similarity=0.35,
    )
    assert result == expected
