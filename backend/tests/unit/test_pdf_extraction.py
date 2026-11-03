from collections.abc import Callable

import pytest

from app.core.errors import ErrorCode
from app.ingestion.errors import IngestionError
from app.ingestion.pdf_extraction import clean_page_text, extract_pages, remove_repeated_lines
from tests.conftest import sample_pdf
from tests.pdf_factory import make_encrypted_pdf, make_text_pdf

POLICY_TEXT = (
    "Artículo 1. Objeto del seguro\nLa Aseguradora garantiza los daños materiales cubiertos."
)


def test_text_is_extracted_per_page() -> None:
    data = make_text_pdf([POLICY_TEXT, "Artículo 2. Daños por agua\nSe cubren escapes de agua."])

    extracted = extract_pages(data, max_pages=10)

    assert extracted.page_count == 2
    assert "Objeto del seguro" in extracted.pages[0]
    assert "escapes de agua" in extracted.pages[1]


def test_real_sample_policy() -> None:
    extracted = extract_pages(sample_pdf("marea-hogar-condicionado-2025.pdf"), max_pages=300)

    assert extracted.page_count == 6
    assert any("Artículo 4. Daños por agua" in page for page in extracted.pages)
    # running footer "Marea Seguros · MH-CG-2025 · Página N" is removed as boilerplate
    assert not any("Página" in page for page in extracted.pages)


@pytest.mark.parametrize(
    "data", [b"%PDF-1.7\nthis is not really a pdf", b"%PDF-" + bytes(range(256)) * 4]
)
def test_corrupt_pdf_is_a_permanent_error(data: bytes) -> None:
    with pytest.raises(IngestionError) as excinfo:
        extract_pages(data, max_pages=10)
    assert excinfo.value.code is ErrorCode.PDF_CORRUPT


def test_pdf_without_text_layer_is_rejected(make_blank_pdf: Callable[[], bytes]) -> None:
    with pytest.raises(IngestionError) as excinfo:
        extract_pages(make_blank_pdf(), max_pages=10)
    assert excinfo.value.code is ErrorCode.PDF_NO_TEXT


def test_password_protected_pdf_is_rejected() -> None:
    with pytest.raises(IngestionError) as excinfo:
        extract_pages(make_encrypted_pdf(POLICY_TEXT, user_password="secreta"), max_pages=10)
    assert excinfo.value.code is ErrorCode.PDF_ENCRYPTED


def test_owner_only_protection_is_still_readable() -> None:
    extracted = extract_pages(make_encrypted_pdf(POLICY_TEXT, user_password=""), max_pages=10)
    assert "Objeto del seguro" in extracted.pages[0]


def test_too_many_pages_is_rejected() -> None:
    with pytest.raises(IngestionError) as excinfo:
        extract_pages(make_text_pdf([POLICY_TEXT, POLICY_TEXT]), max_pages=1)
    assert excinfo.value.code is ErrorCode.PDF_TOO_MANY_PAGES


def test_clean_page_text_repairs_layout_artifacts() -> None:
    raw = "Las cober-\nturas   incluyen\u00a0daños por\nagua.\nLa franquicia es fija.\n\n\n\nFin."

    assert clean_page_text(raw) == (
        "Las coberturas incluyen daños por agua.\nLa franquicia es fija.\n\nFin."
    )


def test_running_headers_and_page_numbers_are_removed() -> None:
    pages = [
        f"Condicionado General\nCláusula {n}\nTexto propio de la página {n}.\n{n} de 4"
        for n in range(1, 5)
    ]

    cleaned = remove_repeated_lines(pages)

    # The verbatim header and the "N de 4" numbering go; content differing only by a number
    # ("Cláusula 1", "Cláusula 2"...) stays.
    assert cleaned == [f"Cláusula {n}\nTexto propio de la página {n}." for n in range(1, 5)]


def test_page_footer_with_changing_number_is_removed() -> None:
    pages = [f"Marea Seguros · Página {n}\nContenido {n}" for n in range(1, 5)]

    assert remove_repeated_lines(pages) == [f"Contenido {n}" for n in range(1, 5)]
    assert remove_repeated_lines(pages[:2]) == pages[:2]  # too few pages to tell
