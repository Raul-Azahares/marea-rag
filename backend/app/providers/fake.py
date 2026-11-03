"""Deterministic, offline providers for tests and the key-less demo."""

import hashlib
import math
from collections import Counter
from collections.abc import Sequence

from app.providers.base import EmbeddingBatch
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
