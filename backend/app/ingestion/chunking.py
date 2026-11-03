"""Structure-aware chunking for insurance policies.

1. Pages are concatenated, keeping a map of where each page starts, so every chunk knows the
   pages it spans: a citation says "pp. 3-4" when a clause crosses a page break.
2. The text is cut at the headings policies are organised by: chapter-level ("CAPÍTULO II",
   all-caps titles) and clause-level ("Artículo 4. Daños por agua", "Cláusula 3", "3.2 Robo").
   A chunk never mixes two clauses, so a citation always points to exactly one clause.
3. Each clause is packed sentence by sentence up to `chunk_size` characters. Consecutive
   chunks of the same clause share up to `overlap` characters of *whole* sentences, so an idea
   cut by a boundary is still retrievable with its context.
4. Pure and deterministic: same text and parameters, same chunks. Chunk ids are derived from
   the index, so re-ingesting a document reproduces identical rows.
"""

import bisect
import re
from dataclasses import dataclass

PAGE_SEPARATOR = "\n\n"

_CHAPTER_HEADING = re.compile(
    r"^(?:(?i:cap[ií]tulo|t[ií]tulo|secci[oó]n|anexo|ap[eé]ndice)\b.{0,100}"
    r"|[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ ,:;()/-]{3,70})$",
    re.MULTILINE,
)
_CLAUSE_HEADING = re.compile(
    r"^(?:(?i:art[ií]culo|cl[aá]usula)\s+[\dIVXLC]+\b.{0,100}"
    r"|\d{1,2}(?:\.\d{1,2}){1,3}\.?\s+[A-ZÁÉÍÓÚÑ][^\n]{2,80}(?<![.,;:]))$",
    re.MULTILINE,
)
_SENTENCE_BOUNDARY = re.compile(
    r"(?<=[.!?;:])\s+(?=[«\"¿¡(\[A-ZÁÉÍÓÚÑ•\u2013-])"  # end punctuation, then a new sentence
    r"|\n\s*\n"  # paragraph break
    r"|\n(?=\s*(?:[•\u2013*-]|[a-z0-9]{1,3}[).]\s))"  # line starting a list item: "a) ", "1. "
)


@dataclass(frozen=True)
class ChunkDraft:
    index: int
    content: str
    heading_path: tuple[str, ...]  # (chapter, clause), most specific last; may be empty
    page_start: int  # 1-based, inclusive
    page_end: int

    @property
    def section(self) -> str | None:
        return self.heading_path[-1] if self.heading_path else None


@dataclass(frozen=True)
class _Span:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class _Section:
    heading_path: tuple[str, ...]
    start: int
    end: int
    body_start: int  # first character after the heading line


def chunk_document(
    pages: list[str], *, chunk_size: int, overlap: int, min_size: int
) -> list[ChunkDraft]:
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    text, page_starts = _join_pages(pages)
    drafts: list[ChunkDraft] = []
    for section in _split_sections(text):
        for group in _pack(
            text, section, chunk_size=chunk_size, overlap=overlap, min_size=min_size
        ):
            start, end = group[0].start, group[-1].end
            content = text[start:end].strip()
            if not content:
                continue
            drafts.append(
                ChunkDraft(
                    index=len(drafts),
                    content=content,
                    heading_path=section.heading_path,
                    page_start=_page_at(page_starts, start),
                    page_end=_page_at(page_starts, end - 1),
                )
            )
    return drafts


# ----------------------------------------------------------------------------- pages
def _join_pages(pages: list[str]) -> tuple[str, list[int]]:
    starts, parts, offset = [], [], 0
    for page in pages:
        starts.append(offset)
        parts.append(page)
        offset += len(page) + len(PAGE_SEPARATOR)
    return PAGE_SEPARATOR.join(parts), starts


def _page_at(page_starts: list[int], offset: int) -> int:
    return bisect.bisect_right(page_starts, max(offset, 0))  # 1-based page number


# -------------------------------------------------------------------------- sections
def _split_sections(text: str) -> list[_Section]:
    headings: list[tuple[int, int, str, str]] = []  # (start, end, level, heading text)
    for level, pattern in (("chapter", _CHAPTER_HEADING), ("clause", _CLAUSE_HEADING)):
        headings += [
            (m.start(), m.end(), level, m.group(0).strip()) for m in pattern.finditer(text)
        ]
    headings.sort()

    sections: list[_Section] = []
    if not headings or headings[0][0] > 0:
        first = headings[0][0] if headings else len(text)
        sections.append(_Section((), 0, first, 0))  # preamble before any heading

    chapter: str | None = None
    for i, (start, line_end, level, heading) in enumerate(headings):
        end = headings[i + 1][0] if i + 1 < len(headings) else len(text)
        if level == "chapter":
            chapter = heading[:300]
            path: tuple[str, ...] = (chapter,)
        else:
            path = (chapter, heading[:300]) if chapter else (heading[:300],)
        if level == "chapter" and not text[line_end:end].strip():
            continue  # a bare chapter title: it lives on in the heading path of its clauses
        sections.append(_Section(path, start, end, line_end))
    return sections


# --------------------------------------------------------------------------- packing
def _units(text: str, section: _Section, chunk_size: int) -> list[_Span]:
    """Heading line + sentences of the body; over-long sentences split at word boundaries."""
    spans = [_Span(section.start, section.body_start)] if section.body_start > section.start else []
    cursor = section.body_start
    for match in _SENTENCE_BOUNDARY.finditer(text, section.body_start, section.end):
        spans.append(_Span(cursor, match.start()))
        cursor = match.end()
    spans.append(_Span(cursor, section.end))

    units: list[_Span] = []
    for span in spans:
        if not text[span.start : span.end].strip():
            continue
        units.extend(_split_long(text, span, chunk_size))
    return units


def _split_long(text: str, span: _Span, chunk_size: int) -> list[_Span]:
    if span.length <= chunk_size:
        return [span]
    pieces, start = [], span.start
    while span.end - start > chunk_size:
        cut = text.rfind(" ", start, start + chunk_size)
        if cut <= start:  # no space at all: hard cut
            cut = start + chunk_size
        pieces.append(_Span(start, cut))
        start = cut
    pieces.append(_Span(start, span.end))
    return pieces


def _pack(
    text: str, section: _Section, *, chunk_size: int, overlap: int, min_size: int
) -> list[list[_Span]]:
    groups: list[list[_Span]] = []
    current: list[_Span] = []
    for unit in _units(text, section, chunk_size):
        if current and unit.end - current[0].start > chunk_size:
            groups.append(current)
            current = [*_overlap_tail(current, overlap, unit, chunk_size), unit]
        else:
            current.append(unit)
    if current:
        groups.append(current)

    # A short trailing piece of a long clause reads better merged into its predecessor.
    if len(groups) >= 2:
        last, previous = groups[-1], groups[-2]
        if (
            last[-1].end - last[0].start < min_size
            and last[-1].end - previous[0].start <= chunk_size + min_size
        ):
            groups[-2] = previous + [u for u in last if u.start >= previous[-1].end]
            groups.pop()
    return groups


def _overlap_tail(
    group: list[_Span], overlap: int, next_unit: _Span, chunk_size: int
) -> list[_Span]:
    """Whole trailing sentences of `group` worth at most `overlap` characters."""
    tail: list[_Span] = []
    for unit in reversed(group):
        if group[-1].end - unit.start > overlap:
            break
        tail.insert(0, unit)
    if len(tail) == len(group) or (tail and next_unit.end - tail[0].start > chunk_size):
        return []  # repeating the whole previous chunk, or overflowing, is not "overlap"
    return tail
