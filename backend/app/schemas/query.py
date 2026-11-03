"""Contract of the question-answering endpoint and of the source-fragment viewer."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AnswerStatus = Literal[
    "answered",  # every claim verified against the sources
    "partial",  # only part of the question is covered (or unverifiable claims were dropped)
    "conflicting_evidence",  # sources disagree: both positions shown, none chosen
    "insufficient_evidence",  # nothing in the documents supports an answer
    "llm_unavailable",  # model down or rate-limited: relevant fragments returned instead
]


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    document_ids: list[uuid.UUID] | None = Field(
        default=None, max_length=50, description="Restrict the search to these documents."
    )

    @field_validator("question")
    @classmethod
    def _collapse_whitespace(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 3:
            raise ValueError("question is too short")
        return value


class Citation(BaseModel):
    ref: int = Field(description="Number used in the answer text: [1], [2]...")
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    document_version: int
    section: str | None
    page_start: int
    page_end: int
    quote: str = Field(description="Verbatim excerpt of the fragment backing the claim.")
    exact_match: bool = Field(
        description="True: the quote matched verbatim (ignoring case, accents and spacing). "
        "False: near-verbatim match."
    )


class Statement(BaseModel):
    text: str
    citation_refs: list[int]


class RetrievedFragment(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    document_version: int
    section: str | None
    page_start: int
    page_end: int
    similarity: float | None
    text_rank: float | None
    score: float
    cited: bool
    flagged: bool = Field(description="Contains instruction-like text (possible prompt injection).")
    preview: str


class ValidationIssue(BaseModel):
    code: str
    detail: str
    statement_index: int | None


class ValidationReport(BaseModel):
    passed: bool
    attempts: int = Field(description="LLM calls made (1 + repair attempts); 0 if none.")
    degraded: bool = Field(description="True if unverifiable claims were dropped.")
    issues: list[ValidationIssue]


class Usage(BaseModel):
    model: str | None
    input_tokens: int | None
    output_tokens: int | None


class QueryResponse(BaseModel):
    status: AnswerStatus
    answer: str = Field(description="Plain-text rendering with [n] citation markers.")
    no_evidence: bool = Field(description="True when no verifiable answer could be given.")
    confidence: Literal["high", "medium", "low", "none"]
    statements: list[Statement]
    citations: list[Citation]
    retrieved: list[RetrievedFragment] = Field(description="Every fragment considered, for review.")
    warnings: list[str]
    validation: ValidationReport
    usage: Usage
    trace_id: str | None
    latency_ms: int


class ChunkOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    document_version: int
    document_superseded: bool
    section: str | None
    page_start: int
    page_end: int
    content: str
    flags: list[str]
