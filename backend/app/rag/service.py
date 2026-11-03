"""Answering a question, step by step:

1. Embed the question. If the embedding provider is down, degrade to full-text search only.
2. Hybrid retrieval over the current documents.
3. Evidence gate: if nothing is close enough, answer "no evidence" without calling the LLM.
   That saves cost and leaves the model no room to hallucinate.
4. Generation with structured output, then validation of every citation.
5. If validation fails: one repair attempt with precise feedback. If that also fails, degrade
   (keep only the verified claims) or reject (nothing verifiable left).
6. Confidence is computed from observable signals, not self-reported by the model.

Policy text, questions and answers never reach logs or span attributes, only lengths, ids,
counts and scores.
"""

import asyncio
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.telemetry import current_trace_id
from app.ingestion.injection import SUSPECTED_INJECTION
from app.providers.base import ChatMessage, ChatModel, EmbeddingProvider, ProviderError
from app.rag.confidence import compute_confidence
from app.rag.models import LLMAnswer, LLMStatus, RetrievedChunk
from app.rag.prompt import build_messages, fragment_ids, repair_message
from app.rag.retrieval import RetrievalMode, retrieve
from app.rag.validation import ValidationResult, VerifiedStatement, validate_answer
from app.schemas.query import (
    AnswerStatus,
    Citation,
    QueryResponse,
    RetrievedFragment,
    Statement,
    Usage,
    ValidationIssue,
    ValidationReport,
)
from app.text_utils import normalize_for_match

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)

NO_EVIDENCE_ANSWER = (
    "No he encontrado información suficiente en los documentos cargados para responder a esta "
    "pregunta."
)
LLM_UNAVAILABLE_ANSWER = (
    "El asistente no está disponible en este momento. Estos son los fragmentos más relevantes "
    "que he encontrado, para que puedas revisarlos."
)


@dataclass(frozen=True)
class _Generation:
    result: ValidationResult
    attempts: int
    model: str | None
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class _Outcome:
    status: AnswerStatus
    statements: tuple[VerifiedStatement, ...]
    llm_status: LLMStatus | None
    degraded: bool
    generation: _Generation | None


class QueryService:
    def __init__(
        self,
        session: AsyncSession,
        embedder: EmbeddingProvider,
        chat: ChatModel,
        settings: Settings,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._chat = chat
        self._settings = settings

    async def answer(
        self, question: str, document_ids: Sequence[uuid.UUID] | None = None
    ) -> QueryResponse:
        started = time.perf_counter()
        warnings: list[str] = []
        trace.get_current_span().set_attribute("marea.rag.question_length", len(question))

        query_vector = await self._embed_question(question, warnings)
        chunks, best_similarity = await self._retrieve(question, query_vector, document_ids)

        if self._lacks_evidence(chunks, best_similarity, has_vector=query_vector is not None):
            outcome = _Outcome("insufficient_evidence", (), None, degraded=False, generation=None)
            return self._respond(outcome, chunks, warnings, best_similarity, started)

        fragments = dict(zip(fragment_ids(len(chunks)), chunks, strict=True))
        try:
            async with asyncio.timeout(self._settings.query_timeout_s):
                generation = await self._generate_validated(question, fragments)
        except (ProviderError, TimeoutError) as exc:
            logger.warning("llm_unavailable", error_type=type(exc).__name__)
            outcome = _Outcome("llm_unavailable", (), None, degraded=False, generation=None)
            return self._respond(outcome, chunks, warnings, best_similarity, started)

        return self._respond(
            self._decide(generation, warnings), chunks, warnings, best_similarity, started
        )

    # ------------------------------------------------------------------ steps
    async def _embed_question(self, question: str, warnings: list[str]) -> list[float] | None:
        with tracer.start_as_current_span("rag.embed_query") as span:
            span.set_attribute("gen_ai.operation.name", "embeddings")
            span.set_attribute("gen_ai.request.model", self._embedder.model_name)
            try:
                return await self._embedder.embed_query(question)
            except ProviderError as exc:
                span.set_attribute("marea.rag.degraded_to_text_search", True)
                logger.warning("query_embedding_unavailable", error_type=type(exc).__name__)
                warnings.append(
                    "La búsqueda semántica no está disponible; se ha usado solo la búsqueda "
                    "por texto."
                )
                return None

    async def _retrieve(
        self,
        question: str,
        query_vector: list[float] | None,
        document_ids: Sequence[uuid.UUID] | None,
    ) -> tuple[list[RetrievedChunk], float | None]:
        mode: RetrievalMode = self._settings.retrieval_mode if query_vector is not None else "text"
        with tracer.start_as_current_span("rag.retrieve") as span:
            chunks = await retrieve(
                self._session,
                query_text=question,
                query_vector=query_vector,
                embedding_model=self._embedder.model_name,
                mode=mode,
                candidates=self._settings.retrieval_candidates,
                top_k=self._settings.retrieval_top_k,
                document_ids=document_ids,
            )
            best = max((c.similarity for c in chunks if c.similarity is not None), default=None)
            span.set_attribute("marea.rag.retrieval_mode", mode)
            span.set_attribute("marea.rag.retrieved_count", len(chunks))
            span.set_attribute("marea.rag.min_similarity", self._settings.retrieval_min_similarity)
            if best is not None:
                span.set_attribute("marea.rag.best_similarity", round(best, 4))
        return chunks, best

    def _lacks_evidence(
        self, chunks: list[RetrievedChunk], best_similarity: float | None, *, has_vector: bool
    ) -> bool:
        if not chunks:
            return True
        # With vectors available, "nothing is close enough" is the refusal signal. In text-only
        # fallback there are no similarities: the LLM and the validator decide.
        if has_vector:
            return (
                best_similarity is None or best_similarity < self._settings.retrieval_min_similarity
            )
        return False

    async def _generate_validated(
        self, question: str, fragments: dict[str, RetrievedChunk]
    ) -> _Generation:
        messages: list[ChatMessage] = build_messages(question, fragments)
        input_tokens = output_tokens = 0
        model: str | None = None
        max_attempts = self._settings.validation_max_retries + 1
        for attempt in range(1, max_attempts + 1):
            with tracer.start_as_current_span("rag.generate") as span:
                span.set_attribute("gen_ai.operation.name", "chat")
                span.set_attribute("gen_ai.request.model", self._chat.model_name)
                span.set_attribute("gen_ai.request.temperature", self._settings.llm_temperature)
                span.set_attribute("marea.rag.attempt", attempt)
                result = await self._chat.complete(messages, response_schema=LLMAnswer)
                model = result.model
                span.set_attribute("gen_ai.response.model", result.model)
                if result.input_tokens is not None:
                    span.set_attribute("gen_ai.usage.input_tokens", result.input_tokens)
                    input_tokens += result.input_tokens
                if result.output_tokens is not None:
                    span.set_attribute("gen_ai.usage.output_tokens", result.output_tokens)
                    output_tokens += result.output_tokens

            with tracer.start_as_current_span("rag.validate") as span:
                validation = validate_answer(
                    result.content, fragments, min_quote_score=self._settings.quote_min_score
                )
                span.set_attribute("marea.rag.validation_passed", validation.passed)
                span.set_attribute("marea.rag.violation_count", len(validation.violations))
                if validation.violations:
                    span.set_attribute(
                        "marea.rag.violation_codes",
                        sorted({v.code.value for v in validation.violations}),
                    )

            if validation.passed or attempt == max_attempts:
                return _Generation(validation, attempt, model, input_tokens, output_tokens)
            messages = [
                *messages,
                ChatMessage("assistant", result.content),
                repair_message([v.detail for v in validation.violations], list(fragments)),
            ]
        raise AssertionError("unreachable")  # pragma: no cover

    def _decide(self, generation: _Generation, warnings: list[str]) -> _Outcome:
        result = generation.result
        if result.passed:
            status: AnswerStatus = result.status or "insufficient_evidence"
            return _Outcome(status, result.statements, result.status, False, generation)
        if result.statements:
            # Degrade: keep only what verifies, and say so.
            warnings.append(
                "Se omitieron afirmaciones que no se pudieron verificar contra los documentos."
            )
            status = "partial" if result.status in (None, "answered") else result.status
            return _Outcome(status, result.statements, result.status, True, generation)
        # Reject: nothing verifiable survived even after the repair attempt.
        warnings.append(
            "El modelo no produjo una respuesta verificable con las fuentes; revisa los "
            "fragmentos recuperados."
        )
        return _Outcome("insufficient_evidence", (), result.status, True, generation)

    # --------------------------------------------------------------- response
    def _respond(
        self,
        outcome: _Outcome,
        chunks: list[RetrievedChunk],
        warnings: list[str],
        best_similarity: float | None,
        started: float,
    ) -> QueryResponse:
        citations: list[Citation] = []
        refs: dict[tuple[uuid.UUID, str], int] = {}
        statements: list[Statement] = []
        for verified in outcome.statements:
            statement_refs = []
            for citation in verified.citations:
                key = (citation.chunk.chunk_id, normalize_for_match(citation.quote))
                if key not in refs:
                    refs[key] = len(citations) + 1
                    chunk = citation.chunk
                    citations.append(
                        Citation(
                            ref=refs[key],
                            chunk_id=chunk.chunk_id,
                            document_id=chunk.document_id,
                            document_title=chunk.document_title,
                            document_version=chunk.document_version,
                            section=chunk.section,
                            page_start=chunk.page_start,
                            page_end=chunk.page_end,
                            quote=citation.quote,
                            exact_match=citation.exact,
                        )
                    )
                statement_refs.append(refs[key])
            statements.append(
                Statement(text=verified.text, citation_refs=sorted(set(statement_refs)))
            )

        cited = {c.chunk_id for c in citations}
        retrieved = [
            RetrievedFragment(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_title=c.document_title,
                document_version=c.document_version,
                section=c.section,
                page_start=c.page_start,
                page_end=c.page_end,
                similarity=c.similarity,
                text_rank=c.text_rank,
                score=c.score,
                cited=c.chunk_id in cited,
                flagged=SUSPECTED_INJECTION in c.flags,
                preview=c.content[:240],
            )
            for c in chunks
        ]
        warnings = [*warnings, *self._status_warnings(outcome)]
        # Only relevant when the model produced an answer with a suspicious fragment in its
        # context; the per-fragment `flagged` badge covers the review list in every case.
        if statements and any(fragment.flagged for fragment in retrieved):
            warnings.append(
                "La respuesta se generó con un fragmento que contiene texto con apariencia de "
                "instrucciones (posible inyección). Revisa la fuente antes de usarla."
            )

        generation = outcome.generation
        confidence = compute_confidence(
            outcome.statements,
            status=outcome.llm_status,
            attempts=generation.attempts if generation else 0,
            degraded=outcome.degraded,
            best_similarity=best_similarity,
            high_similarity=self._settings.confidence_high_similarity,
        )
        latency_ms = round((time.perf_counter() - started) * 1000)
        response = QueryResponse(
            status=outcome.status,
            answer=self._render(outcome.status, statements),
            no_evidence=not statements and outcome.status != "llm_unavailable",
            confidence=confidence,
            statements=statements,
            citations=citations,
            retrieved=retrieved,
            warnings=warnings,
            validation=ValidationReport(
                passed=generation.result.passed if generation else True,
                attempts=generation.attempts if generation else 0,
                degraded=outcome.degraded,
                issues=[
                    ValidationIssue(code=v.code, detail=v.detail, statement_index=v.statement_index)
                    for v in (generation.result.violations if generation else ())
                ],
            ),
            usage=Usage(
                model=generation.model if generation else None,
                input_tokens=generation.input_tokens if generation else None,
                output_tokens=generation.output_tokens if generation else None,
            ),
            trace_id=current_trace_id(),
            latency_ms=latency_ms,
        )
        self._record(response, best_similarity)
        return response

    @staticmethod
    def _status_warnings(outcome: _Outcome) -> list[str]:
        if outcome.status == "conflicting_evidence":
            return [
                "Los documentos recuperados se contradicen: revisa las fuentes antes de "
                "responder al cliente."
            ]
        if outcome.status == "partial" and not outcome.degraded:
            return [
                "La respuesta solo cubre parte de la pregunta; los documentos no recogen el resto."
            ]
        return []

    @staticmethod
    def _render(status: AnswerStatus, statements: list[Statement]) -> str:
        if status == "llm_unavailable":
            return LLM_UNAVAILABLE_ANSWER
        if not statements:
            return NO_EVIDENCE_ANSWER
        return " ".join(
            f"{s.text} {''.join(f'[{ref}]' for ref in s.citation_refs)}" for s in statements
        )

    @staticmethod
    def _record(response: QueryResponse, best_similarity: float | None) -> None:
        span = trace.get_current_span()
        span.set_attribute("marea.rag.status", response.status)
        span.set_attribute("marea.rag.confidence", response.confidence)
        span.set_attribute("marea.rag.citation_count", len(response.citations))
        span.set_attribute("marea.rag.attempts", response.validation.attempts)
        logger.info(
            "query_answered",
            status=response.status,
            confidence=response.confidence,
            attempts=response.validation.attempts,
            degraded=response.validation.degraded,
            citations=len(response.citations),
            retrieved=len(response.retrieved),
            best_similarity=round(best_similarity, 4) if best_similarity is not None else None,
            latency_ms=response.latency_ms,
        )
