import itertools

import pytest

from app.ingestion.chunking import ChunkDraft, chunk_document

PAGES = [
    "MAREA SEGUROS\nCondicionado de prueba para tests.",
    "CAPÍTULO I. COBERTURAS\n"
    "Artículo 1. Incendio\n"
    "Se cubren los daños por incendio. La indemnización alcanza el 100 % de la suma.\n"
    "Artículo 2. Daños por agua\n"
    "Se cubren los escapes accidentales de agua de las conducciones.",
    "La franquicia por siniestro es de 150 euros.\n"
    "CAPÍTULO II. EXCLUSIONES\n"
    "Artículo 3. Exclusiones generales\n"
    "No se cubre el desgaste ni la falta de mantenimiento.",
]


def chunk(
    pages: list[str], size: int = 900, overlap: int = 150, min_size: int = 200
) -> list[ChunkDraft]:
    return chunk_document(pages, chunk_size=size, overlap=overlap, min_size=min_size)


def by_section(drafts: list[ChunkDraft], fragment: str) -> ChunkDraft:
    return next(d for d in drafts if d.section and fragment in d.section)


def test_one_chunk_per_clause_and_never_mixing_clauses() -> None:
    drafts = chunk(PAGES)

    sections = [d.section for d in drafts]
    assert sections == [
        "MAREA SEGUROS",
        "Artículo 1. Incendio",
        "Artículo 2. Daños por agua",
        "Artículo 3. Exclusiones generales",
    ]
    assert "agua" not in by_section(drafts, "Incendio").content
    assert "incendio" not in by_section(drafts, "agua").content.lower()


def test_clause_crossing_a_page_break_reports_both_pages() -> None:
    water = by_section(chunk(PAGES), "agua")

    assert (water.page_start, water.page_end) == (2, 3)
    assert water.content.endswith("150 euros.")


def test_chapter_titles_become_context_not_chunks() -> None:
    drafts = chunk(PAGES)

    assert all(d.content != "CAPÍTULO I. COBERTURAS" for d in drafts)
    assert by_section(drafts, "Incendio").heading_path == (
        "CAPÍTULO I. COBERTURAS",
        "Artículo 1. Incendio",
    )
    assert by_section(drafts, "Exclusiones").heading_path[0] == "CAPÍTULO II. EXCLUSIONES"


def test_text_without_headings_is_a_single_untitled_section() -> None:
    drafts = chunk(["Documento sin encabezados. Solo hay un párrafo de texto corrido."])

    assert len(drafts) == 1
    assert drafts[0].section is None
    assert drafts[0].heading_path == ()


@pytest.mark.parametrize(
    ("line", "is_heading"),
    [
        ("Cláusula 4. Robo y expoliación", True),
        ("3.2 Daños por agua", True),
        ("Artículo 7 bis. Daños eléctricos", True),
        ("1. El tomador deberá comunicar el siniestro en siete días.", False),
        ("Según el artículo anterior, la franquicia es de 150 euros.", False),
    ],
)
def test_heading_detection(line: str, is_heading: bool) -> None:
    drafts = chunk([f"Texto inicial del documento.\n{line}\nCuerpo de la sección con detalle."])

    assert (drafts[-1].section == line) is is_heading


def test_long_clause_is_packed_by_sentences_with_overlap() -> None:
    sentences = [
        f"La garantía número {i} tiene un límite propio de {i * 100} euros." for i in range(40)
    ]
    drafts = chunk(
        [f"Artículo 9. Límites\n{' '.join(sentences)}"], size=400, overlap=120, min_size=100
    )

    assert len(drafts) > 3
    assert all(len(d.content) <= 400 + 100 for d in drafts)  # size + merge allowance
    for previous, current in itertools.pairwise(drafts):
        # whole sentences repeated across the boundary, never a cut in the middle
        first_sentence = current.content.split(". ")[0] + "."
        assert first_sentence in previous.content
        assert current.content[0].isupper()


def test_sentence_longer_than_the_chunk_is_split_at_word_boundaries() -> None:
    words = [f"palabra{i}" for i in range(400)]
    drafts = chunk([" ".join(words)], size=300, overlap=50, min_size=50)

    assert len(drafts) > 1
    assert all(len(d.content) <= 300 + 50 for d in drafts)
    rebuilt = " ".join(d.content for d in drafts).split()
    assert rebuilt == words  # nothing lost, no word cut in half


def test_small_trailing_piece_is_merged_into_the_previous_chunk() -> None:
    body = "Primera frase con bastante contenido sobre la cobertura. " * 6 + "Fin."
    drafts = chunk([f"Artículo 1. Prueba\n{body}"], size=300, overlap=0, min_size=80)

    assert drafts[-1].content.endswith("Fin.")
    assert len(drafts[-1].content) >= 80


def test_output_is_deterministic_and_indexed() -> None:
    first, second = chunk(PAGES), chunk(PAGES)

    assert first == second
    assert [d.index for d in first] == list(range(len(first)))


def test_empty_pages_produce_no_chunks() -> None:
    assert chunk(["", "   ", "\n"]) == []


def test_overlap_must_be_smaller_than_chunk_size() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk(PAGES, size=100, overlap=100)
