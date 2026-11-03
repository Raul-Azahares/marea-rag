"""Evaluation reports: Markdown for people (eval/reports/*.md) and JSON for diffs and tooling."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evaluation.dataset import Category
from evaluation.metrics import (
    GateCheck,
    QuestionResult,
    ThresholdAnalysis,
    by_category,
    retrieval_summary,
)

METRICS: dict[str, str] = {
    "hit_at_1": "hit@1: la fuente esperada es el primer fragmento",
    "hit_at_3": "hit@3: la fuente esperada está entre los 3 primeros",
    "hit_at_6": "hit@6: la fuente esperada llega al modelo (top-6)",
    "mrr": "MRR: media de 1/posición de la primera fuente correcta",
    "source_recall": "Recall de fuentes: parte de las fuentes esperadas recuperada",
    "answer_rate": "Respondibles que se respondieron",
    "refusal_rate": "Sin respuesta en los documentos que se rechazaron",
    "gate_refusals": "…de ellas, rechazadas por la compuerta sin llamar al LLM",
    "abstention_accuracy": "Decisión correcta de responder o abstenerse",
    "fact_recall": "Recall de hechos obligatorios en la respuesta",
    "citation_precision": "Citas que apuntan a una fuente esperada",
    "first_pass_validation_rate": "Respuestas del LLM válidas a la primera",
    "repaired_answers": "Respuestas válidas tras el reintento de reparación",
    "degraded_answers": "Respuestas degradadas (se omitieron afirmaciones sin verificar)",
    "forbidden_fact_answers": "Respuestas con hechos prohibidos (versión antigua, inyección)",
    "superseded_citations": "Citas a una versión reemplazada",
    "flagged_citations": "Citas a fragmentos marcados como posible inyección",
    "llm_errors": "Preguntas con el LLM no disponible",
    "latency_p50_ms": "Latencia p50 (ms)",
    "latency_p95_ms": "Latencia p95 (ms)",
}

CATEGORY_COUNTS: dict[Category, str] = {
    "answerable": "respondibles",
    "version": "de versión",
    "multi_document": "multidocumento",
    "injection": "de inyección",
    "unanswerable": "sin respuesta",
}

CATEGORY_NAMES: dict[Category, str] = {
    "answerable": "Respondibles",
    "version": "Versión (2026 reemplaza a 2025)",
    "multi_document": "Multidocumento",
    "injection": "Inyección (anexo adversarial)",
    "unanswerable": "Sin respuesta",
}


@dataclass(frozen=True)
class RunInfo:
    label: str
    embedding_model: str
    chat_model: str | None
    chunk_size: int
    chunk_overlap: int
    context_header: bool
    retrieval_mode: str
    top_k: int
    min_similarity: float
    chunk_count: int
    created_at: str = ""

    def stamped(self) -> "RunInfo":
        return RunInfo(**{**self.__dict__, "created_at": timestamp()})


def timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _yes(flag: bool) -> str:
    return "sí" if flag else "no"


def fmt(value: float | int | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return str(value)
    return f"{value:.2f}".replace(".", ",")


def _rows(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def render_run(
    info: RunInfo,
    results: Sequence[QuestionResult],
    summary: dict[str, float | int | None],
    threshold: ThresholdAnalysis,
    gate: Sequence[GateCheck],
) -> str:
    counts: dict[Category, int] = {}
    for r in results:
        counts[r.question.category] = counts.get(r.question.category, 0) + 1
    limits = {c.metric: c for c in gate}
    lines = [
        f"# Evaluación · {info.label}",
        "",
        f"- Fecha: {info.created_at}",
        f"- Modelos: embeddings `{info.embedding_model}`, LLM `{info.chat_model}`"
        + _answered_by(results),
        f"- Índice: {info.chunk_count} fragmentos (chunks de {info.chunk_size} caracteres, "
        f"solape {info.chunk_overlap}, cabecera contextual {_yes(info.context_header)}); "
        f"recuperación {info.retrieval_mode}, top-{info.top_k}; τ = {fmt(info.min_similarity)}",
        f"- Preguntas: {len(results)} ("
        + ", ".join(f"{n} {CATEGORY_COUNTS[c]}" for c, n in counts.items())
        + ")",
        "",
        "## Resumen",
        "",
    ]
    rows = []
    for metric, label in METRICS.items():
        check = limits.get(metric)
        gate_cell = ""
        if check:
            sign = "≥" if check.kind == "min" else "≤"
            gate_cell = f"{sign} {fmt(check.limit)} {'✅' if check.passed else '❌'}"
        rows.append([label, fmt(summary.get(metric)), gate_cell])
    lines += _rows(["Métrica", "Valor", "Quality gate"], rows)

    lines += ["", "## Por categoría", ""]
    table = by_category(results)
    lines += _rows(
        ["Categoría", "Preguntas", "Decisión correcta", "hit@6", "MRR", "Recall de hechos"],
        [
            [
                CATEGORY_NAMES[c],
                fmt(int(v["questions"] or 0)),
                fmt(v["correct_decision"]),
                fmt(v["hit_at_6"]),
                fmt(v["mrr"]),
                fmt(v["fact_recall"]),
            ]
            for c, v in table.items()
        ],
    )

    lines += ["", "## Compuerta de evidencia (τ)", ""]
    lines += _threshold_section(threshold, info.min_similarity)

    failing = [r for r in results if r.problems]
    lines += ["", f"## Preguntas con algún problema ({len(failing)} de {len(results)})", ""]
    lines += [f"- `{r.question.id}`: {'; '.join(r.problems)}" for r in failing] or ["Ninguna."]

    lines += ["", "## Detalle por pregunta", ""]
    lines += _rows(
        ["Pregunta", "Estado", "Fuente en", "Hechos", "Citas en fuente", "Similitud", "ms"],
        [
            [
                f"`{r.question.id}`",
                r.status or "—",
                f"#{r.first_relevant_rank}" if r.first_relevant_rank else "—",
                f"{len(r.facts_found)}/{len(r.question.required_facts)}"
                if r.question.required_facts
                else "—",
                f"{r.relevant_citations}/{len(r.citations)}" if r.citations else "—",
                fmt(r.best_similarity),
                str(r.latency_ms),
            ]
            for r in results
        ],
    )
    lines += ["", "Métricas y criterios: [eval/README.md](../README.md).", ""]
    return "\n".join(lines)


def _answered_by(results: Sequence[QuestionResult]) -> str:
    """Which models actually answered: a fallback model shows up here."""
    counts: dict[str, int] = {}
    for r in results:
        if r.model:
            counts[r.model] = counts.get(r.model, 0) + 1
    if not counts:
        return ""
    return " (respondieron: " + ", ".join(f"`{m}`: {n}" for m, n in counts.items()) + ")"


def _threshold_section(analysis: ThresholdAnalysis, current: float) -> list[str]:
    def describe(values: list[float]) -> str:
        if not values:
            return "—"
        middle = values[len(values) // 2]
        return f"mín. {fmt(values[0])} · mediana {fmt(middle)} · máx. {fmt(values[-1])}"

    lines = [
        "Mejor similitud coseno entre la pregunta y los fragmentos recuperados:",
        "",
        f"- Respondibles ({len(analysis.answerable)}): {describe(analysis.answerable)}",
        f"- Sin respuesta ({len(analysis.unanswerable)}): {describe(analysis.unanswerable)}",
    ]
    if analysis.safe_threshold is not None:
        lines += [
            f"- τ seguro (no rechaza ninguna respondible, margen 0,02): "
            f"**{fmt(analysis.safe_threshold)}**; bloquea "
            f"{analysis.blocked_unanswerable(analysis.safe_threshold)} de "
            f"{len(analysis.unanswerable)} sin respuesta antes del LLM",
            f"- τ con mejor exactitud equilibrada: {fmt(analysis.best_threshold)} "
            f"({fmt(analysis.best_balanced_accuracy)})",
            f"- τ configurado: {fmt(current)}; bloquea "
            f"{analysis.blocked_unanswerable(current)} de {len(analysis.unanswerable)}",
        ]
    return lines


def render_sweep(
    embedding_model: str,
    rows: Sequence[tuple[int, int, bool, int, dict[str, float | None]]],
    modes: Sequence[tuple[str, dict[str, float | None]]],
    ranks: dict[str, dict[str, int | None]],
    created_at: str,
) -> str:
    lines = [
        f"# Barrido de chunking · embeddings `{embedding_model}`",
        "",
        f"- Fecha: {created_at}",
        "- Solo recuperación (sin LLM), sobre las preguntas respondibles del dataset; "
        "recuperación híbrida, top-6. El índice se reconstruye con el pipeline real para cada "
        "configuración.",
        "",
    ]
    lines += _rows(
        [
            "Tamaño",
            "Solape",
            "Cabecera",
            "Fragmentos",
            "hit@1",
            "hit@3",
            "hit@6",
            "MRR",
            "Recall fuentes",
        ],
        [
            [
                str(size),
                str(overlap),
                "sí" if header else "no",
                str(chunks),
                fmt(m["hit_at_1"]),
                fmt(m["hit_at_3"]),
                fmt(m["hit_at_6"]),
                fmt(m["mrr"]),
                fmt(m["source_recall"]),
            ]
            for size, overlap, header, chunks, m in rows
        ],
    )
    lines += ["", "## Modo de recuperación (configuración por defecto)", ""]
    lines += _rows(
        ["Modo", "hit@1", "hit@3", "hit@6", "MRR", "Recall fuentes"],
        [
            [
                mode,
                fmt(m["hit_at_1"]),
                fmt(m["hit_at_3"]),
                fmt(m["hit_at_6"]),
                fmt(m["mrr"]),
                fmt(m["source_recall"]),
            ]
            for mode, m in modes
        ],
    )
    names = list(ranks)
    disagreements = (
        [qid for qid in ranks.get(names[0], {}) if len({ranks[n].get(qid) for n in names}) > 1]
        if names
        else []
    )
    if disagreements:
        lines += [
            "",
            "Preguntas en las que los modos no coinciden (posición de la primera fuente "
            "correcta; — = fuera del top-6):",
            "",
        ]
        lines += _rows(
            ["Pregunta", *names],
            [
                [f"`{qid}`", *(f"#{ranks[n][qid]}" if ranks[n].get(qid) else "—" for n in names)]
                for qid in disagreements
            ],
        )
    lines.append("")
    return "\n".join(lines)


def run_json(
    info: RunInfo,
    results: Sequence[QuestionResult],
    summary: dict[str, float | int | None],
    threshold: ThresholdAnalysis,
    gate: Sequence[GateCheck],
) -> dict[str, Any]:
    return {
        "run": info.__dict__,
        "summary": summary,
        "categories": by_category(results),
        "retrieval": retrieval_summary(results),
        "threshold": {
            "answerable": threshold.answerable,
            "unanswerable": threshold.unanswerable,
            "safe": threshold.safe_threshold,
            "best": threshold.best_threshold,
            "best_balanced_accuracy": threshold.best_balanced_accuracy,
        },
        "gate": [
            {
                "metric": c.metric,
                "value": c.value,
                "limit": c.limit,
                "kind": c.kind,
                "passed": c.passed,
            }
            for c in gate
        ],
        "questions": [
            {
                "id": r.question.id,
                "category": r.question.category,
                "status": r.status,
                "answered": r.answered,
                "first_relevant_rank": r.first_relevant_rank,
                "best_similarity": r.best_similarity,
                "facts_found": r.facts_found,
                "forbidden_found": r.forbidden_found,
                "citations": [{"document": c.document, "section": c.section} for c in r.citations],
                "attempts": r.attempts,
                "latency_ms": r.latency_ms,
                "problems": r.problems,
                "answer": r.answer,
                "quotes": list(r.quotes),
            }
            for r in results
        ],
    }


def write(path_stem: Path, markdown: str, data: dict[str, Any] | None = None) -> None:
    path_stem.parent.mkdir(parents=True, exist_ok=True)
    path_stem.with_suffix(".md").write_text(markdown, encoding="utf-8")
    if data is not None:
        path_stem.with_suffix(".json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
