import math

from app.providers.fake import HashingEmbeddingProvider


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))  # vectors are unit-length


def test_vectors_have_the_configured_size_and_unit_norm() -> None:
    vector = HashingEmbeddingProvider(768).embed("Daños por agua en la vivienda")

    assert len(vector) == 768
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0)


def test_same_text_same_vector_across_instances() -> None:
    # Stable across processes too: blake2b, not the per-process salted hash().
    text = "franquicia de daños por agua"
    assert HashingEmbeddingProvider(768).embed(text) == HashingEmbeddingProvider(768).embed(text)


def test_case_and_accent_insensitive() -> None:
    provider = HashingEmbeddingProvider(768)
    assert provider.embed("Póliza DAÑOS") == provider.embed("poliza daños")


def test_related_texts_are_closer_than_unrelated_ones() -> None:
    provider = HashingEmbeddingProvider(768)
    question = provider.embed("¿Cubre la póliza los daños por agua en la segunda vivienda?")
    related = provider.embed("La garantía de daños por agua se extiende a la segunda vivienda.")
    unrelated = provider.embed("El vehículo de sustitución se presta durante cinco días.")

    assert cosine(question, related) > 0.3
    assert cosine(question, related) > cosine(question, unrelated) + 0.2


def test_text_without_content_words_still_gets_a_valid_vector() -> None:
    vector = HashingEmbeddingProvider(16).embed("de la y el")
    assert vector == [1.0] + [0.0] * 15


async def test_query_and_document_embeddings_match() -> None:
    provider = HashingEmbeddingProvider(64)
    batch = provider.embed_documents(["robo con fuerza"])

    assert batch.vectors[0] == await provider.embed_query("robo con fuerza")
    assert batch.input_tokens is not None
    assert batch.input_tokens > 0
