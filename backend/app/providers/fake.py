"""Deterministic, offline providers for tests and the key-less demo."""

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel

from app.providers.base import ChatMessage, ChatResult, EmbeddingBatch
from app.rag.prompt import parse_fragments, parse_question
from app.text_utils import content_words, estimate_tokens

_WORD_WEIGHT = 1.0
_TRIGRAM_WEIGHT = 0.3


class HashingEmbeddingProvider:
    """Feature-hashing embeddings over words and character trigrams.

    Not random noise: texts that share words (accent-insensitive) or word stems get similar
    vectors, so retrieval in the demo and in tests behaves meaningfully, if lexically rather
    than semantically.

    Uses blake2b, never Python's built-in `hash()`. That one is salted per process
    (PYTHONHASHSEED), so the API and the worker would produce different vectors for the same
    text.
    """

    model_name = "fake-hashing-v1"

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        return EmbeddingBatch(
            vectors=[self.embed(text) for text in texts],
            input_tokens=sum(estimate_tokens(text) for text in texts),
        )

    async def embed_query(self, text: str) -> list[float]:
        return self.embed(text)

    def embed(self, text: str) -> list[float]:
        features: Counter[str] = Counter()
        for word in content_words(text):
            features[f"w:{word}"] += 1
            padded = f"^{word}$"
            features.update(f"c:{padded[i : i + 3]}" for i in range(len(padded) - 2))

        vector = [0.0] * self.dimensions
        for feature, count in features.items():
            digest = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest())
            index = digest % self.dimensions
            sign = 1.0 if digest >> 63 else -1.0  # signed hashing limits collision bias
            weight = _WORD_WEIGHT if feature.startswith("w:") else _TRIGRAM_WEIGHT
            vector[index] += sign * weight * (1.0 + math.log(count))

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:  # no content words: a fixed unit vector (never NaN in pgvector)
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]


_SENTENCE_END = re.compile(r"(?<=[.;:])\s+")
_STEM = 5  # comparing 5-letter prefixes absorbs plurals and verb forms (vivienda/viviendas)


def _stems(text: str) -> set[str]:
    return {word[:_STEM] for word in content_words(text)}


class FakeChatModel:
    """Deterministic, extractive stand-in for an LLM, used by the tests and the key-less demo.

    It reads the prompt the way a model would (fragments plus question) and picks the sentences
    that cover the most of the question's content words. It answers in exactly the JSON format a
    real model must produce, quoting those sentences verbatim. If nothing overlaps enough, it
    declares insufficient evidence. The real pipeline (prompt building, parsing, citation
    validation) runs unchanged on top of it.
    """

    model_name = "fake-extractive-v1"
    MIN_COVERAGE = 0.34  # share of the question's content words a sentence must contain
    MAX_STATEMENTS = 2

    async def complete(
        self, messages: Sequence[ChatMessage], *, response_schema: type[BaseModel]
    ) -> ChatResult:
        prompt = next(m.content for m in messages if m.role == "user")
        question_stems = _stems(parse_question(prompt))
        candidates: list[tuple[float, int, str, str]] = []  # (coverage, order, fragment, sentence)
        for fragment_id, text in parse_fragments(prompt).items():
            for sentence in _SENTENCE_END.split(text.replace("\n", " ")):
                if not question_stems or len(sentence.split()) < 5:
                    continue
                coverage = len(_stems(sentence) & question_stems) / len(question_stems)
                candidates.append((coverage, len(candidates), fragment_id, sentence.strip()))

        best = max((c[0] for c in candidates), default=0.0)
        threshold = max(self.MIN_COVERAGE, 0.8 * best)
        chosen = sorted((c for c in candidates if c[0] >= threshold), key=lambda c: (-c[0], c[1]))[
            : self.MAX_STATEMENTS
        ]
        answer = {
            "status": "answered" if chosen else "insufficient_evidence",
            "statements": [
                {"text": sentence, "citations": [{"fragment_id": fragment_id, "quote": sentence}]}
                for _, _, fragment_id, sentence in chosen
            ],
        }
        content = json.dumps(answer, ensure_ascii=False)
        return ChatResult(
            content=content,
            model=self.model_name,
            input_tokens=sum(estimate_tokens(m.content) for m in messages),
            output_tokens=estimate_tokens(content),
        )
