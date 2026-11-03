"""Answer confidence, computed by the system instead of asked to the model.

LLMs are poorly calibrated about their own certainty. These signals are observable:
- how close the best evidence is (retrieval similarity);
- whether the answer passed validation on the first try or needed a repair or degradation;
- whether every quote matched verbatim;
- whether the model itself reported a partial or contradictory answer.
"""

from collections.abc import Sequence
from typing import Literal

from app.rag.models import LLMStatus
from app.rag.validation import VerifiedStatement

Confidence = Literal["high", "medium", "low", "none"]


def compute_confidence(
    statements: Sequence[VerifiedStatement],
    *,
    status: LLMStatus | None,
    attempts: int,
    degraded: bool,
    best_similarity: float | None,
    high_similarity: float,
) -> Confidence:
    if not statements:
        return "none"
    if degraded or status in ("partial", "conflicting_evidence"):
        return "low"
    all_exact = all(citation.exact for s in statements for citation in s.citations)
    strong_evidence = best_similarity is None or best_similarity >= high_similarity
    if attempts == 1 and all_exact and strong_evidence:
        return "high"
    return "medium"
