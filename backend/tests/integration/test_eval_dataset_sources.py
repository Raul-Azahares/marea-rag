"""The evaluation dataset points at clauses by their heading. If the chunker or the sample
PDFs change how a heading comes out, the evaluation would silently score against nothing:
this test fails first."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk
from app.db.session import get_sync_engine
from evaluation.dataset import load_dataset

pytestmark = pytest.mark.integration

# Dataset corpus keys -> keys of the `corpus` fixture (same sample PDFs).
FIXTURE_KEYS = {
    "hogar_2025": "hogar_v1",
    "hogar_2026": "hogar_v2",
    "auto": "auto",
    "annex": "annex",
}


def test_every_expected_source_is_a_real_section(corpus: dict[str, uuid.UUID]) -> None:
    with Session(get_sync_engine()) as session:
        rows = session.execute(select(Chunk.document_id, Chunk.section)).all()
    sections = {(document_id, section) for document_id, section in rows}

    missing = [
        f"{q.id}: {s.document} / {s.section}"
        for q in load_dataset().questions
        for s in q.sources
        if (corpus[FIXTURE_KEYS[s.document]], s.section) not in sections
    ]
    assert not missing
