"""Scoring: pure functions over what the system returned for each question.

Retrieval is scored on the fragments the pipeline actually put in front of the model (top-k
after fusion); answers on the verified statements and citations it returned.
"""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.text_utils import normalize_for_match
from evaluation.dataset import Category, Question, Source

HIT_KS = (1, 3, 6)


@dataclass(frozen=True)
class Fragment:
    """A retrieved or cited fragment, mapped back to the corpus."""

    document: str | None  # corpus key; None for a document outside the corpus
    section: str | None
    similarity: float | None = None
    flagged: bool = False  # suspected prompt injection


@dataclass(frozen=True)
class QuestionResult:
    question: Question
    retrieved: list[Fragment]
    status: str | None = None  # None in retrieval-only runs
    answer: str = ""
    quotes: tuple[str, ...] = ()  # verbatim quotes shown under the answer
    citations: list[Fragment] = field(default_factory=list)
    attempts: int = 0  # LLM calls; 0 = refused by the evidence gate (or retrieval-only)
    validation_passed: bool = True
    degraded: bool = False
    latency_ms: int = 0
    model: str | None = None  # the model that answered (a fallback, if the primary failed)
    superseded_documents: frozenset[str] = frozenset()
    always_forbidden: tuple[str, ...] = ()

    # ------------------------------------------------------------- retrieval
    @property
    def first_relevant_rank(self) -> int | None:
        for rank, fragment in enumerate(self.retrieved, start=1):
            if is_relevant(fragment, self.question.sources):
                return rank
        return None

    def hit_at(self, k: int) -> bool:
        rank = self.first_relevant_rank
        return rank is not None and rank <= k

    @property
    def reciprocal_rank(self) -> float:
        rank = self.first_relevant_rank
        return 1.0 / rank if rank else 0.0

    @property
    def source_recall(self) -> float:
        """Share of the expected sources present among the retrieved fragments."""
        if not self.question.sources:
            return 0.0
        found = sum(
            any(is_relevant(f, [source]) for f in self.retrieved)
            for source in self.question.sources
        )
        return found / len(self.question.sources)

    @property
    def best_similarity(self) -> float | None:
        return max((f.similarity for f in self.retrieved if f.similarity is not None), default=None)

    # --------------------------------------------------------------- answers
    @property
    def answered(self) -> bool:
        return bool(self.citations) and self.status not in (None, "insufficient_evidence")

    @property
    def refused_by_gate(self) -> bool:
        return self.status == "insufficient_evidence" and self.attempts == 0

    @property
    def correct_decision(self) -> bool:
        return self.answered == self.question.answerable

    @property
    def visible_text(self) -> str:
        """What the agent reads: the statements and, right below them, the verbatim quotes."""
        return " ".join((self.answer, *self.quotes))

    @property
    def facts_found(self) -> list[str]:
        return [f for f in self.question.required_facts if contains_fact(self.visible_text, f)]

    @property
    def fact_recall(self) -> float | None:
        facts = self.question.required_facts
        if not facts:
            return None
        return len(self.facts_found) / len(facts) if self.answered else 0.0

    @property
    def forbidden_found(self) -> list[str]:
        candidates = [*self.question.forbidden_facts, *self.always_forbidden]
        return [f for f in candidates if contains_fact(self.visible_text, f)]

    @property
    def relevant_citations(self) -> int:
        return sum(is_relevant(c, self.question.sources) for c in self.citations)

    @property
    def superseded_citations(self) -> int:
        return sum(c.document in self.superseded_documents for c in self.citations)

    @property
    def flagged_citations(self) -> int:
        return sum(c.flagged for c in self.citations)

    @property
    def problems(self) -> list[str]:
        """Human-readable reasons why this question did not fully pass."""
        found: list[str] = []
        q = self.question
        if q.answerable and self.status is not None and not self.answered:
            found.append(f"no respondió ({self.status})")
        if not q.answerable and self.answered:
            found.append("respondió una pregunta sin respuesta en los documentos")
        if q.answerable and not self.hit_at(HIT_KS[-1]):
            found.append(f"la fuente esperada no está en el top-{HIT_KS[-1]}")
        if self.status is not None and self.answered:
            missing = [f for f in q.required_facts if f not in self.facts_found]
            if missing:
                found.append("faltan hechos: " + ", ".join(missing))
            off = len(self.citations) - self.relevant_citations
            if q.sources and off:
                found.append(f"{off} cita(s) fuera de las fuentes esperadas")
        if self.forbidden_found:
            found.append("contiene hechos prohibidos: " + ", ".join(self.forbidden_found))
        if self.superseded_citations:
            found.append("cita una versión reemplazada")
        if self.flagged_citations:
            found.append("cita un fragmento marcado como posible inyección")
        if self.status == "llm_unavailable":
            found.append("el modelo no estuvo disponible")
        return found


def is_relevant(fragment: Fragment, sources: Sequence[Source]) -> bool:
    section = normalize_for_match(fragment.section or "")
    return any(
        fragment.document == s.document and section == normalize_for_match(s.section)
        for s in sources
    )


def contains_fact(text: str, fact: str) -> bool:
    """Whole-word match ignoring case, accents, punctuation and spacing ("10 días" never
    matches "110 días"). "€" reads as "euros", as a model may write either."""

    def canonical(value: str) -> str:
        return normalize_for_match(value.replace("€", " euros "))

    return f" {canonical(fact)} " in f" {canonical(text)} "


# --------------------------------------------------------------------- aggregation
def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _percentile(values: Sequence[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def retrieval_summary(results: Sequence[QuestionResult]) -> dict[str, float | None]:
    scored = [r for r in results if r.question.answerable]
    summary: dict[str, float | None] = {
        f"hit_at_{k}": _mean([float(r.hit_at(k)) for r in scored]) for k in HIT_KS
    }
    summary["mrr"] = _mean([r.reciprocal_rank for r in scored])
    summary["source_recall"] = _mean([r.source_recall for r in scored])
    return summary


def summarize(results: Sequence[QuestionResult]) -> dict[str, float | int | None]:
    answerable = [r for r in results if r.question.answerable]
    unanswerable = [r for r in results if not r.question.answerable]
    with_llm = [r for r in results if r.attempts > 0]
    scored_citations = [r for r in answerable if r.answered]
    total_citations = sum(len(r.citations) for r in scored_citations)
    summary: dict[str, float | int | None] = {"questions": len(results)}
    summary.update(retrieval_summary(results))
    summary.update(
        {
            "answer_rate": _ratio(sum(r.answered for r in answerable), len(answerable)),
            "refusal_rate": _ratio(sum(not r.answered for r in unanswerable), len(unanswerable)),
            "gate_refusals": sum(r.refused_by_gate for r in unanswerable),
            "abstention_accuracy": _ratio(sum(r.correct_decision for r in results), len(results)),
            "fact_recall": _mean(
                [recall for r in answerable if (recall := r.fact_recall) is not None]
            ),
            "citation_precision": _ratio(
                sum(r.relevant_citations for r in scored_citations), total_citations
            ),
            "first_pass_validation_rate": _ratio(
                sum(r.attempts == 1 and r.validation_passed for r in with_llm), len(with_llm)
            ),
            "repaired_answers": sum(r.attempts > 1 and r.validation_passed for r in with_llm),
            "degraded_answers": sum(r.degraded for r in results),
            "forbidden_fact_answers": sum(bool(r.forbidden_found) for r in results),
            "superseded_citations": sum(r.superseded_citations for r in results),
            "flagged_citations": sum(r.flagged_citations for r in results),
            "llm_errors": sum(r.status == "llm_unavailable" for r in results),
            "latency_p50_ms": _percentile([r.latency_ms for r in results], 0.5),
            "latency_p95_ms": _percentile([r.latency_ms for r in results], 0.95),
        }
    )
    return summary


def by_category(results: Sequence[QuestionResult]) -> dict[Category, dict[str, float | None]]:
    categories: dict[Category, list[QuestionResult]] = {}
    for result in results:
        categories.setdefault(result.question.category, []).append(result)
    table: dict[Category, dict[str, float | None]] = {}
    for category, items in categories.items():
        answerable = [r for r in items if r.question.answerable]
        table[category] = {
            "questions": len(items),
            "correct_decision": _ratio(sum(r.correct_decision for r in items), len(items)),
            "hit_at_6": _mean([float(r.hit_at(6)) for r in answerable]),
            "mrr": _mean([r.reciprocal_rank for r in answerable]),
            "fact_recall": _mean(
                [recall for r in answerable if (recall := r.fact_recall) is not None]
            ),
        }
    return table


@dataclass(frozen=True)
class GateCheck:
    metric: str
    value: float | int | None
    limit: float
    kind: str  # "min" or "max"

    @property
    def passed(self) -> bool:
        if self.value is None:
            return False
        return self.value >= self.limit if self.kind == "min" else self.value <= self.limit


def check_gate(
    summary: dict[str, float | int | None], minimums: dict[str, float], maximums: dict[str, float]
) -> list[GateCheck]:
    checks = [GateCheck(m, summary.get(m), limit, "min") for m, limit in minimums.items()]
    checks += [GateCheck(m, summary.get(m), limit, "max") for m, limit in maximums.items()]
    return checks


@dataclass(frozen=True)
class ThresholdAnalysis:
    """How well a similarity threshold separates answerable from unanswerable questions."""

    answerable: list[float]
    unanswerable: list[float]
    safe_threshold: float | None  # highest τ that never refuses an answerable question
    best_threshold: float | None  # τ with the best balanced accuracy
    best_balanced_accuracy: float | None

    def blocked_unanswerable(self, threshold: float) -> int:
        return sum(s < threshold for s in self.unanswerable)


def analyse_threshold(
    results: Sequence[QuestionResult], *, margin: float = 0.02
) -> ThresholdAnalysis:
    answerable = sorted(
        s for r in results if r.question.answerable and (s := r.best_similarity) is not None
    )
    unanswerable = sorted(
        s for r in results if not r.question.answerable and (s := r.best_similarity) is not None
    )
    if not answerable:
        return ThresholdAnalysis(answerable, unanswerable, None, None, None)
    safe = round(max(0.0, answerable[0] - margin), 2)
    best, best_score = None, -1.0
    for step in range(0, 101):
        tau = step / 100
        kept = sum(s >= tau for s in answerable) / len(answerable)
        rejected = sum(s < tau for s in unanswerable) / len(unanswerable) if unanswerable else 1.0
        score = (kept + rejected) / 2
        if score > best_score:
            best, best_score = tau, score
    return ThresholdAnalysis(answerable, unanswerable, safe, best, round(best_score, 4))
