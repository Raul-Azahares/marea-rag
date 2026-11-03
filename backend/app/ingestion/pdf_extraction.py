"""PDF text extraction with pypdf (pure Python, BSD licence).

Why not Docling: our policies are born-digital PDFs. Docling's layout models need torch
(gigabytes, slow on CPU) to recover structure that heading rules recover here (see
chunking.py). A pure-Python parser also fails with exceptions we can classify, rather than
crashing the worker process. PDFs without a text layer (scans) are rejected with a clear
error; OCR is explicitly out of scope for the MVP.
"""

import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from pypdf import PasswordType, PdfReader

from app.core.errors import ErrorCode
from app.ingestion.errors import IngestionError

MIN_TEXT_CHARS = 40  # less than this in the whole document = no usable text layer
_HYPHENATED_BREAK = re.compile(r"(\w)-\n(\w)")
_SOFT_WRAP = re.compile(r"(?<![.:;!?])\n(?=[a-záéíóúñü(])")
_SPACES = re.compile(r"[ \t\u00a0]+")  # including no-break spaces
_BLANK_LINES = re.compile(r"\n{3,}")
_DIGITS = re.compile(r"\d+")
# Page numbering ending a line, once digits are replaced by "#": "... página #", "pág. # de #",
# "page #", "# de #", "#". Anchored at the end so prose that mentions a page is not matched.
_PAGE_NUMBERING = re.compile(r"(\b(p[aá]g(ina)?|page)\.?\s*|^)#(\s*(de|/|of)\s*#)?$")


@dataclass(frozen=True)
class ExtractedDocument:
    pages: list[str]  # index 0 is page 1

    @property
    def page_count(self) -> int:
        return len(self.pages)


def extract_pages(data: bytes, *, max_pages: int) -> ExtractedDocument:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
            raise IngestionError(ErrorCode.PDF_ENCRYPTED, "El PDF está protegido con contraseña.")
        page_count = len(reader.pages)
    except IngestionError:
        raise
    except Exception as exc:  # untrusted input: any parser failure means "unreadable"
        raise IngestionError(
            ErrorCode.PDF_CORRUPT, "El PDF está dañado o no se puede leer."
        ) from exc

    if page_count > max_pages:
        raise IngestionError(
            ErrorCode.PDF_TOO_MANY_PAGES,
            f"El PDF tiene {page_count} páginas; el máximo admitido es {max_pages}.",
        )

    raw_pages = []
    for page in reader.pages:
        try:
            raw_pages.append(page.extract_text() or "")
        except Exception:  # one broken page must not sink the whole document
            raw_pages.append("")

    pages = remove_repeated_lines([clean_page_text(text) for text in raw_pages])
    if sum(len(page) for page in pages) < MIN_TEXT_CHARS:
        raise IngestionError(
            ErrorCode.PDF_NO_TEXT,
            "El PDF no contiene texto extraíble (¿es un escaneo?). El OCR no está soportado.",
        )
    return ExtractedDocument(pages=pages)


def clean_page_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\x00", "")
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _HYPHENATED_BREAK.sub(r"\1\2", text)  # "cober-\nturas" -> "coberturas"
    text = _SOFT_WRAP.sub(" ", text)  # re-join lines wrapped mid-sentence
    return _BLANK_LINES.sub("\n\n", text).strip()


def remove_repeated_lines(pages: list[str], *, min_pages: int = 3, ratio: float = 0.6) -> list[str]:
    """Drop running headers/footers ("Marea Seguros · Página 3") that would pollute chunks.

    A short line is boilerplate if it repeats verbatim on most pages, or if it is page
    numbering that repeats with only the number changing. Content that merely differs by a
    number ("Cláusula 3", "Cláusula 4") is kept.
    """
    if len(pages) < min_pages:
        return pages

    def key(line: str) -> str:
        literal = line.strip().lower()
        numbered = _DIGITS.sub("#", literal)
        return numbered if _PAGE_NUMBERING.search(numbered) else literal

    page_counts: Counter[str] = Counter()
    for page in pages:
        page_counts.update({key(line) for line in page.splitlines() if 0 < len(line) < 100})
    boilerplate = {k for k, n in page_counts.items() if n >= ratio * len(pages)}
    if not boilerplate:
        return pages
    return [
        "\n".join(line for line in page.splitlines() if key(line) not in boilerplate).strip()
        for page in pages
    ]
