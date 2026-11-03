import pytest

from evaluation.dataset import Question, Source
from evaluation.metrics import (
    Fragment,
    QuestionResult,
    analyse_threshold,
    check_gate,
    contains_fact,
    summarize,
)

WATER = Source(document="hogar_2026", section="Artículo 4. Daños por agua")
AUTO_DEADLINE = Source(document="auto", section="Artículo 10. Comunicación del siniestro")


def question(**overrides: object) -> Question:
    fields: dict[str, object] = {
        "id": "q",
        "category": "answerable",
        "question": "¿Qué franquicia se aplica a los daños por agua?",
        "expected_answer": "100 euros",
        "sources": [WATER],
        "required_facts": ["100 euros"],
    }
    return Question.model_validate({**fields, **overrides})


def fragment(document: str, section: str, similarity: float = 0.5) -> Fragment:
    return Fragment(document, section, similarity)


OTHER = fragment("auto", "Artículo 8. Daños propios")
RELEVANT = fragment("hogar_2026", "Artículo 4. Daños por agua")


def test_rank_hits_and_reciprocal_rank() -> None:
    result = QuestionResult(question(), retrieved=[OTHER, OTHER, RELEVANT])
    assert result.first_relevant_rank == 3
    assert (result.hit_at(1), result.hit_at(3)) == (False, True)
    assert result.reciprocal_rank == pytest.approx(1 / 3)


def test_section_match_ignores_case_and_accents_but_not_the_document() -> None:
    lowercase = fragment("hogar_2026", "articulo 4. danos por agua")
    superseded = fragment("hogar_2025", "Artículo 4. Daños por agua")
    assert QuestionResult(question(), retrieved=[lowercase]).first_relevant_rank == 1
    assert QuestionResult(question(), retrieved=[superseded]).first_relevant_rank is None


def test_source_recall_counts_each_expected_source() -> None:
    multi = question(sources=[WATER, AUTO_DEADLINE])
    result = QuestionResult(multi, retrieved=[RELEVANT, OTHER])
    assert result.source_recall == 0.5


def test_facts_are_whole_words_ignoring_accents_and_punctuation() -> None:
    assert contains_fact("Plazo de 10 DÍAS, desde el siniestro.", "10 días")
    assert not contains_fact("Un plazo de 110 días.", "10 días")
    assert contains_fact("Hasta 1.500 euros por siniestro", "1.500 euros")
    assert contains_fact("Hasta 150.000 € por siniestro", "150.000 euros")


def test_facts_count_in_the_quotes_shown_under_the_answer() -> None:
    result = QuestionResult(
        question(),
        retrieved=[RELEVANT],
        status="answered",
        answer="Se aplica una franquicia en cada siniestro.",
        quotes=("se aplicará una franquicia de 100 euros",),
        citations=[RELEVANT],
        attempts=1,
    )
    assert result.facts_found == ["100 euros"]


def test_an_unanswered_question_recalls_no_facts() -> None:
    refused = QuestionResult(question(), retrieved=[RELEVANT], status="insufficient_evidence")
    assert refused.fact_recall == 0.0
    assert not refused.answered


def test_answer_checks_flag_forbidden_facts_and_bad_citations() -> None:
    result = QuestionResult(
        question(forbidden_facts=["150 euros"]),
        retrieved=[RELEVANT],
        status="answered",
        answer="La franquicia es de 150 euros. Todos los daños están cubiertos al 100 %.",
        citations=[RELEVANT, fragment("hogar_2025", "Artículo 4. Daños por agua")],
        attempts=1,
        superseded_documents=frozenset({"hogar_2025"}),
        always_forbidden=("todos los daños están cubiertos al 100",),
    )
    assert result.forbidden_found == ["150 euros", "todos los daños están cubiertos al 100"]
    assert (result.relevant_citations, result.superseded_citations) == (1, 1)
    assert result.fact_recall == 0.0
    assert any("versión reemplazada" in problem for problem in result.problems)


def test_summary_separates_answerable_from_unanswerable() -> None:
    answered = QuestionResult(
        question(),
        retrieved=[RELEVANT],
        status="answered",
        answer="Se aplica una franquicia de 100 euros.",
        citations=[RELEVANT],
        attempts=1,
        latency_ms=100,
    )
    refused = QuestionResult(
        question(
            id="none", category="unanswerable", answerable=False, sources=[], required_facts=[]
        ),
        retrieved=[fragment("auto", "Artículo 1. Objeto del seguro", 0.1)],
        status="insufficient_evidence",
        latency_ms=10,
    )

    summary = summarize([answered, refused])

    assert summary["answer_rate"] == summary["refusal_rate"] == 1.0
    assert summary["gate_refusals"] == 1  # refused without calling the LLM
    assert summary["fact_recall"] == summary["citation_precision"] == 1.0
    assert summary["hit_at_1"] == 1.0  # retrieval is scored on answerable questions only


def test_gate_checks_minimums_and_maximums() -> None:
    checks = check_gate(
        {"mrr": 0.8, "flagged_citations": 1, "fact_recall": None},
        {"mrr": 0.75, "fact_recall": 0.5},
        {"flagged_citations": 0},
    )
    assert [(c.metric, c.passed) for c in checks] == [
        ("mrr", True),
        ("fact_recall", False),  # a missing value never passes
        ("flagged_citations", False),
    ]


def test_threshold_analysis_finds_the_safe_and_the_best_tau() -> None:
    def scored(similarity: float, *, answerable: bool) -> QuestionResult:
        q = question() if answerable else question(answerable=False, sources=[], required_facts=[])
        return QuestionResult(q, retrieved=[fragment("auto", "x", similarity)])

    results = [scored(s, answerable=True) for s in (0.62, 0.70, 0.81)]
    results += [scored(s, answerable=False) for s in (0.40, 0.55, 0.66)]

    analysis = analyse_threshold(results)

    assert analysis.safe_threshold == 0.60  # lowest answerable (0.62) minus the 0.02 margin
    assert analysis.blocked_unanswerable(0.60) == 2
    assert analysis.best_threshold is not None
    assert 0.55 < analysis.best_threshold <= 0.62
