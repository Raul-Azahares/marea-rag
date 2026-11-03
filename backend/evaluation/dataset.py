"""The evaluation dataset (eval/dataset.yaml): the corpus to index and the questions to ask."""

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = REPO_ROOT / "eval" / "dataset.yaml"

Category = Literal["answerable", "version", "multi_document", "injection", "unanswerable"]


class CorpusDocument(BaseModel):
    key: str
    file: str  # relative to the repository root
    title: str
    version_of: str | None = None  # key of the document this one supersedes


class Source(BaseModel):
    """Where an answer lives: a document of the corpus and the exact heading of the clause."""

    document: str
    section: str


class Question(BaseModel):
    id: str
    category: Category
    question: str
    expected_answer: str
    answerable: bool = True
    sources: list[Source] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    forbidden_facts: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.answerable and not self.sources:
            raise ValueError(f"{self.id}: an answerable question needs its expected sources")
        if not self.answerable and (self.sources or self.required_facts):
            raise ValueError(f"{self.id}: an unanswerable question has no sources or facts")
        return self


class QualityGate(BaseModel):
    min: dict[str, float] = Field(default_factory=dict)
    max: dict[str, float] = Field(default_factory=dict)


class Dataset(BaseModel):
    corpus: list[CorpusDocument]
    always_forbidden: list[str] = Field(default_factory=list)
    questions: list[Question]
    quality_gate: QualityGate = Field(default_factory=QualityGate)

    @model_validator(mode="after")
    def _references(self) -> Self:
        keys: list[str] = []
        for document in self.corpus:
            if document.version_of is not None and document.version_of not in keys:
                raise ValueError(f"{document.key}: version_of must name an earlier document")
            keys.append(document.key)
        if len(set(keys)) != len(keys):
            raise ValueError("corpus keys must be unique")
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("question ids must be unique")
        for question in self.questions:
            for source in question.sources:
                if source.document not in keys:
                    raise ValueError(f"{question.id}: unknown document {source.document!r}")
        return self

    @property
    def superseded_keys(self) -> set[str]:
        return {d.version_of for d in self.corpus if d.version_of is not None}


def load_dataset(path: Path = DEFAULT_DATASET) -> Dataset:
    return Dataset.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
