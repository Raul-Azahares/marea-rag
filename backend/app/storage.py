"""Storage for the uploaded PDFs.

Files are addressed by document id only, never by the user-supplied filename, so there is no
path-traversal surface. Writes are atomic (temp file + rename): the worker can never read a
half-written PDF. The local implementation sits on a Docker volume shared by api (read/write)
and worker (read-only). In production an S3-compatible implementation would replace it.
"""

import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO, Protocol


class FileStorage(Protocol):
    def save(self, document_id: uuid.UUID, source: BinaryIO) -> None: ...

    def read_bytes(self, document_id: uuid.UUID) -> bytes: ...

    def exists(self, document_id: uuid.UUID) -> bool: ...

    def path_for(self, document_id: uuid.UUID) -> Path: ...

    def delete(self, document_id: uuid.UUID) -> None: ...


class LocalFileStorage:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def path_for(self, document_id: uuid.UUID) -> Path:
        return self._base_dir / f"{document_id}.pdf"

    def save(self, document_id: uuid.UUID, source: BinaryIO) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        source.seek(0)
        fd, tmp_name = tempfile.mkstemp(dir=self._base_dir, suffix=".part")
        try:
            with os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(source, out)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp_name, self.path_for(document_id))
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def read_bytes(self, document_id: uuid.UUID) -> bytes:
        return self.path_for(document_id).read_bytes()

    def exists(self, document_id: uuid.UUID) -> bool:
        return self.path_for(document_id).is_file()

    def delete(self, document_id: uuid.UUID) -> None:
        self.path_for(document_id).unlink(missing_ok=True)
