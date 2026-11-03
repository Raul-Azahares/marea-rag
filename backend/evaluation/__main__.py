"""Evaluation command line. Needs the test Postgres (`make test-infra`).

    uv run python -m evaluation run [--llm fake|litellm] [--embeddings fake|litellm]
                                    [--label NAME] [--gate]
    uv run python -m evaluation sweep [--embeddings fake|litellm] [--label NAME]

`run` indexes the sample corpus and asks every question through the full pipeline, then
writes eval/reports/<label>.md and .json. With --gate it exits 1 if a quality-gate threshold
is not met. `sweep` measures retrieval only, rebuilding the index for each chunking setting.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Literal

import sqlalchemy

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.providers.factory import build_chat_model, build_embedding_provider
from app.rag.retrieval import RetrievalMode
from evaluation.dataset import DEFAULT_DATASET, REPO_ROOT, Dataset, load_dataset
from evaluation.harness import (
    answer_questions,
    embed_questions,
    eval_database_url,
    index_corpus,
    reset_database,
    retrieve_only,
)
from evaluation.metrics import analyse_threshold, check_gate, retrieval_summary, summarize
from evaluation.report import RunInfo, fmt, render_run, render_sweep, run_json, timestamp, write

REPORTS_DIR = REPO_ROOT / "eval" / "reports"
SWEEP_SIZES = (500, 900, 1500)
SWEEP_OVERLAPS = (0, 150)
SWEEP_MODES: tuple[RetrievalMode, ...] = ("hybrid", "vector", "text")


def _settings(llm: str | None, embeddings: str | None) -> Settings:
    overrides: dict[str, object] = {}
    if llm:
        overrides["llm_provider"] = llm
    if embeddings:
        overrides["embedding_provider"] = embeddings
    return get_settings().model_copy(update=overrides)


def _label(settings: Settings, label: str | None) -> str:
    if label:
        return label
    fake = settings.llm_provider == "fake" and settings.embedding_provider == "fake"
    return "fake" if fake else "real"


def command_run(args: argparse.Namespace, dataset: Dataset) -> int:
    settings = _settings(args.llm, args.embeddings)
    url = args.database_url or eval_database_url(settings.database_url)
    embedder = build_embedding_provider(settings)
    chat = build_chat_model(settings)

    reset_database(url)
    engine = sqlalchemy.create_engine(url, hide_parameters=True)
    try:
        corpus = index_corpus(dataset, settings, embedder, engine)
    finally:
        engine.dispose()
    results = asyncio.run(
        answer_questions(
            dataset,
            corpus,
            url=url,
            settings=settings,
            embedder=embedder,
            chat=chat,
            pace_s=args.pace,
        )
    )

    summary = summarize(results)
    threshold = analyse_threshold(results)
    gate = check_gate(summary, dataset.quality_gate.min, dataset.quality_gate.max)
    info = RunInfo(
        label=_label(settings, args.label),
        embedding_model=embedder.model_name,
        chat_model=chat.model_name,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        context_header=settings.chunk_context_header,
        retrieval_mode=settings.retrieval_mode,
        top_k=settings.retrieval_top_k,
        min_similarity=settings.retrieval_min_similarity,
        chunk_count=corpus.chunk_count,
    ).stamped()
    stem = REPORTS_DIR / info.label
    write(
        stem,
        render_run(info, results, summary, threshold, gate),
        run_json(info, results, summary, threshold, gate),
    )

    print(f"Evaluación «{info.label}»: {len(results)} preguntas, {corpus.chunk_count} fragmentos")
    for metric in (
        "hit_at_1",
        "hit_at_6",
        "mrr",
        "answer_rate",
        "refusal_rate",
        "fact_recall",
        "citation_precision",
        "forbidden_fact_answers",
        "flagged_citations",
        "latency_p50_ms",
    ):
        print(f"  {metric:<28} {fmt(summary.get(metric))}")
    print(f"  τ seguro {fmt(threshold.safe_threshold)} · τ configurado {fmt(info.min_similarity)}")
    print(f"Informe: {stem.with_suffix('.md').relative_to(REPO_ROOT)}")

    failed = [c for c in gate if not c.passed]
    if gate:
        if failed:
            for check in failed:
                sign = ">=" if check.kind == "min" else "<="
                value, limit = fmt(check.value), fmt(check.limit)
                print(f"Quality gate FALLA: {check.metric} = {value} (exige {sign} {limit})")
        else:
            print(f"Quality gate OK ({len(gate)} comprobaciones)")
    return 1 if args.gate and failed else 0


def command_sweep(args: argparse.Namespace, dataset: Dataset) -> int:
    settings = _settings(None, args.embeddings)
    url = args.database_url or eval_database_url(settings.database_url)
    embedder = build_embedding_provider(settings)
    answerable = dataset.model_copy(
        update={"questions": [q for q in dataset.questions if q.answerable]}
    )
    vectors = asyncio.run(embed_questions(answerable.questions, embedder, pace_s=args.pace))

    rows: list[tuple[int, int, bool, int, dict[str, float | None]]] = []
    modes: list[tuple[str, dict[str, float | None]]] = []
    ranks: dict[str, dict[str, int | None]] = {}  # default configuration: mode -> question -> rank
    default = (settings.chunk_size, settings.chunk_overlap, settings.chunk_context_header)
    configs = (
        [default]
        if args.only_default
        else [(s, o, h) for s in SWEEP_SIZES for o in SWEEP_OVERLAPS for h in (True, False)]
    )
    for size, overlap, header in configs:
        config = settings.model_copy(
            update={"chunk_size": size, "chunk_overlap": overlap, "chunk_context_header": header}
        )
        reset_database(url)
        engine = sqlalchemy.create_engine(url, hide_parameters=True)
        try:
            corpus = index_corpus(answerable, config, embedder, engine)
        finally:
            engine.dispose()
        is_default = (size, overlap, header) == default
        for mode in SWEEP_MODES if is_default else ("hybrid",):
            results = retrieve_only(
                answerable,
                corpus,
                vectors,
                url=url,
                settings=config,
                embedding_model=embedder.model_name,
                mode=mode,
            )
            metrics = retrieval_summary(results)
            if mode == "hybrid":
                rows.append((size, overlap, header, corpus.chunk_count, metrics))
            if is_default:
                modes.append((mode, metrics))
                ranks[mode] = {r.question.id: r.first_relevant_rank for r in results}
        print(
            f"  {size}/{overlap} cabecera={'sí' if header else 'no'}: "
            f"{corpus.chunk_count} fragmentos, MRR {fmt(rows[-1][4]['mrr'])}"
        )

    label = args.label or ("fake" if settings.embedding_provider == "fake" else "real")
    stem = REPORTS_DIR / f"{'modes' if args.only_default else 'sweep'}-{label}"
    created = timestamp()
    write(
        stem,
        render_sweep(embedder.model_name, rows, modes, ranks, created),
        {
            "embedding_model": embedder.model_name,
            "created_at": created,
            "configs": [
                {"chunk_size": s, "overlap": o, "context_header": h, "chunks": c, **m}
                for s, o, h, c, m in rows
            ],
            "modes": [{"mode": mode, **m} for mode, m in modes],
            "default_config_ranks": ranks,
        },
    )
    print(f"Informe: {stem.with_suffix('.md').relative_to(REPO_ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--verbose", action="store_true", help="show the application's warnings")
    parser.add_argument(
        "--database-url", help="default: the test database URL, with database marea_eval"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    providers: tuple[Literal["fake"], Literal["litellm"]] = ("fake", "litellm")

    run = commands.add_parser("run", help="full pipeline: retrieval, generation and validation")
    run.add_argument("--llm", choices=providers)
    run.add_argument("--embeddings", choices=providers)
    run.add_argument("--label", help="report name under eval/reports/ (default: fake or real)")
    run.add_argument("--gate", action="store_true", help="exit 1 if the quality gate fails")
    run.add_argument(
        "--pace", type=float, default=0.0, help="seconds between questions (free-tier quotas)"
    )

    sweep = commands.add_parser("sweep", help="retrieval only, for each chunking configuration")
    sweep.add_argument("--embeddings", choices=providers)
    sweep.add_argument("--label")
    sweep.add_argument("--pace", type=float, default=0.0, help="seconds between query embeddings")
    sweep.add_argument(
        "--only-default", action="store_true", help="only the configured chunking: compare modes"
    )

    args = parser.parse_args(argv)
    # Expected warnings (the annex's suspicious chunk, a degraded answer) belong in the
    # report, not in the console.
    configure_logging(
        service="marea-eval", level="WARNING" if args.verbose else "ERROR", json=False
    )
    dataset = load_dataset(args.dataset)
    if args.command == "run":
        return command_run(args, dataset)
    return command_sweep(args, dataset)


if __name__ == "__main__":
    sys.exit(main())
