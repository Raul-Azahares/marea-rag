"""Retrieval results and the structured output requested from the LLM."""

import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

LLMStatus = Literal["answered", "partial", "insufficient_evidence", "conflicting_evidence"]


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    document_version: int
    content: str
    section: str | None
    page_start: int
    page_end: int
    flags: list[str]
    similarity: float | None  # cosine similarity; None when vector search was unavailable
    text_rank: float | None  # full-text rank; None when the text retriever did not match
    score: float  # reciprocal-rank-fusion score (what the ranking uses)


# --- Structured output: the only shape the LLM is allowed to answer with -------------
class LLMCitation(BaseModel):
    fragment_id: str = Field(description='Id of the cited fragment, e.g. "F2".')
    quote: str = Field(description="Sentence copied verbatim from that fragment.")


class LLMStatement(BaseModel):
    text: str = Field(description="One short, self-contained claim.")
    citations: list[LLMCitation]


class LLMAnswer(BaseModel):
    status: LLMStatus
    statements: list[LLMStatement] = Field(default_factory=list)
