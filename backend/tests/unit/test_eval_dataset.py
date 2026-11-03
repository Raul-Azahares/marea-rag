from typing import Any

import pytest
from pydantic import ValidationError

from evaluation.dataset import REPO_ROOT, Dataset, load_dataset


def test_the_committed_dataset_is_valid_and_covers_every_category() -> None:
    dataset = load_dataset()

    categories = {q.category for q in dataset.questions}
    assert categories == {"answerable", "version", "multi_document", "injection", "unanswerable"}
    assert len(dataset.questions) >= 25
    assert all((REPO_ROOT / d.file).is_file() for d in dataset.corpus)
    assert dataset.superseded_keys == {"hogar_2025"}
    # Answers must come from the current edition: no question expects the superseded one.
    assert not any(s.document == "hogar_2025" for q in dataset.questions for s in q.sources)


def _dataset(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "corpus": [{"key": "auto", "file": "samples/x.pdf", "title": "Auto"}],
        "questions": [
            {
                "id": "q1",
                "category": "answerable",
                "question": "¿?",
                "expected_answer": "-",
                "sources": [{"document": "auto", "section": "Artículo 1"}],
            }
        ],
    }
    return {**base, **overrides}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "questions": [
                    {"id": "q", "category": "answerable", "question": "¿?", "expected_answer": "-"}
                ]
            },
            "needs its expected sources",
        ),
        (
            {
                "questions": [
                    {
                        "id": "q",
                        "category": "answerable",
                        "question": "¿?",
                        "expected_answer": "-",
                        "sources": [{"document": "hogar", "section": "Artículo 1"}],
                    }
                ]
            },
            "unknown document",
        ),
        (
            {"corpus": [{"key": "v2", "file": "x.pdf", "title": "T", "version_of": "v1"}]},
            "version_of must name an earlier document",
        ),
    ],
)
def test_inconsistent_datasets_are_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Dataset.model_validate(_dataset(**overrides))
