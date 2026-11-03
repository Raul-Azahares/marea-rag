import io
import uuid
from pathlib import Path

import pytest

from app.storage import LocalFileStorage


def test_save_read_delete_roundtrip(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "uploads")
    document_id = uuid.uuid4()

    storage.save(document_id, io.BytesIO(b"%PDF-1.7 content"))

    assert storage.exists(document_id)
    assert storage.path_for(document_id) == tmp_path / "uploads" / f"{document_id}.pdf"
    assert storage.read_bytes(document_id) == b"%PDF-1.7 content"
    storage.delete(document_id)
    assert not storage.exists(document_id)


class _ExplodingStream(io.BytesIO):
    def read(self, size: int | None = -1) -> bytes:
        raise OSError("disk full")


def test_failed_write_leaves_no_partial_file(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    document_id = uuid.uuid4()

    with pytest.raises(OSError, match="disk full"):
        storage.save(document_id, _ExplodingStream(b"ignored"))

    assert not storage.exists(document_id)
    assert list(tmp_path.iterdir()) == []  # the temporary .part file was cleaned up
