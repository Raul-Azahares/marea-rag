"""Post-generation validation: every claim must be backed by a verbatim quote taken from a
fragment that was actually retrieved.

Rules:
- R1: each citation points to a retrieved fragment (F1..Fn), never an invented one.
- R2: each statement carries at least one citation; nothing is asserted without one.
- R3: each quote appears in the cited fragment, verbatim after normalising case, accents,
  punctuation and spacing, or as a near-verbatim match (rapidfuzz partial_ratio). Quotes
  shorter than MIN_QUOTE_WORDS are rejected, since a word or two matches almost anywhere.
- R4: the status is consistent: an answer has statements and "insufficient_evidence" has none.
- R5: a fragment flagged as a suspected prompt injection never backs a claim. People can still
  read it in the review list; the model cannot build an answer on it.

A statement survives if at least one of its citations verifies. Any violation still marks
the attempt as failed, which triggers a repair attempt (see QueryService).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, StrEnum

from pydantic import ValidationError
from rapidfuzz import fuzz

from app.ingestion.injection import SUSPECTED_INJECTION
from app.rag.models import LLMAnswer, LLMStatus, RetrievedChunk
from app.text_utils import normalize_for_match

MIN_QUOTE_WORDS = 4
_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class ViolationCode(StrEnum):
    INVALID_OUTPUT = "invalid_output"
    UNKNOWN_FRAGMENT = "unknown_fragment"
    FLAGGED_FRAGMENT = "flagged_fragment"
    MISSING_CITATION = "missing_citation"
    QUOTE_NOT_FOUND = "quote_not_found"
    QUOTE_TOO_SHORT = "quote_too_short"
    EMPTY_ANSWER = "empty_answer"
    INCONSISTENT_STATUS = "inconsistent_status"


class QuoteMatch(Enum):
    EXACT = "exact"
    APPROXIMATE = "approximate"
    NOT_FOUND = "not_found"
    TOO_SHORT = "too_short"


@dataclass(frozen=True)
class Violation:
    code: ViolationCode
    detail: str  # in Spanish: shown to the user and fed back to the model on repair
    statement_index: int | None = None  # 1-based


@dataclass(frozen=True)
class VerifiedCitation:
    fragment_id: str
    chunk: RetrievedChunk
    quote: str
    exact: bool


@dataclass(frozen=True)
class VerifiedStatement:
    text: str
    citations: tuple[VerifiedCitation, ...]


@dataclass(frozen=True)
class ValidationResult:
    status: LLMStatus | None  # None when the output could not even be parsed
    statements: tuple[VerifiedStatement, ...]  # only the statements that survived
    violations: tuple[Violation, ...]

    @property
    def passed(self) -> bool:
        return not self.violations


def match_quote(quote: str, content: str, *, min_score: float) -> QuoteMatch:
    normalized_quote = normalize_for_match(quote)
    if len(normalized_quote.split()) < MIN_QUOTE_WORDS:
        return QuoteMatch.TOO_SHORT
    normalized_content = normalize_for_match(content)
    if f" {normalized_quote} " in f" {normalized_content} ":  # whole words only
        return QuoteMatch.EXACT
    if fuzz.partial_ratio(normalized_quote, normalized_content) >= min_score:
        return QuoteMatch.APPROXIMATE
    return QuoteMatch.NOT_FOUND


def validate_answer(
    raw: str, fragments: Mapping[str, RetrievedChunk], *, min_quote_score: float
) -> ValidationResult:
    try:
        answer = LLMAnswer.model_validate_json(_CODE_FENCE.sub("", raw.strip()))
    except ValidationError:
        violation = Violation(
            ViolationCode.INVALID_OUTPUT, "La salida no es JSON válido con el formato pedido."
        )
        return ValidationResult(None, (), (violation,))

    violations: list[Violation] = []
    statements: list[VerifiedStatement] = []
    for index, statement in enumerate(answer.statements, start=1):
        if not statement.citations:
            violations.append(
                Violation(
                    ViolationCode.MISSING_CITATION,
                    f"La afirmación {index} no tiene ninguna cita.",
                    index,
                )
            )
            continue
        verified: list[VerifiedCitation] = []
        for citation in statement.citations:
            fragment_id = citation.fragment_id.strip().upper()
            chunk = fragments.get(fragment_id)
            if chunk is None:
                violations.append(
                    Violation(
                        ViolationCode.UNKNOWN_FRAGMENT,
                        f"La afirmación {index} cita «{citation.fragment_id}», un fragmento "
                        "que no se proporcionó.",
                        index,
                    )
                )
                continue
            if SUSPECTED_INJECTION in chunk.flags:
                violations.append(
                    Violation(
                        ViolationCode.FLAGGED_FRAGMENT,
                        f"La afirmación {index} cita {fragment_id}, un fragmento marcado como "
                        "posible inyección: no puede respaldar una respuesta.",
                        index,
                    )
                )
                continue
            match = match_quote(citation.quote, chunk.content, min_score=min_quote_score)
            if match is QuoteMatch.TOO_SHORT:
                violations.append(
                    Violation(
                        ViolationCode.QUOTE_TOO_SHORT,
                        f"La cita de la afirmación {index} es demasiado corta para "
                        f"verificarla (mínimo {MIN_QUOTE_WORDS} palabras).",
                        index,
                    )
                )
                continue
            if match is QuoteMatch.NOT_FOUND:
                violations.append(
                    Violation(
                        ViolationCode.QUOTE_NOT_FOUND,
                        f"La cita de la afirmación {index} no aparece literalmente en "
                        f"{fragment_id}.",
                        index,
                    )
                )
                continue
            verified.append(
                VerifiedCitation(
                    fragment_id, chunk, citation.quote.strip(), exact=match is QuoteMatch.EXACT
                )
            )
        if verified and statement.text.strip():
            statements.append(VerifiedStatement(statement.text.strip(), tuple(verified)))

    if answer.status == "insufficient_evidence" and answer.statements:
        violations.append(
            Violation(
                ViolationCode.INCONSISTENT_STATUS,
                "Declara falta de evidencia pero incluye afirmaciones.",
            )
        )
    if answer.status != "insufficient_evidence" and not answer.statements:
        violations.append(
            Violation(
                ViolationCode.EMPTY_ANSWER, "Declara una respuesta pero no incluye afirmaciones."
            )
        )
    return ValidationResult(answer.status, tuple(statements), tuple(violations))
