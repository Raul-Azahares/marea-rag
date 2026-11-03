"""Helpers to seed and inspect documents directly in the test database."""

import hashlib
import io
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Chunk, Document, DocumentStatus
from app.db.session import get_sync_engine
from app.storage import LocalFileStorage


def storage() -> LocalFileStorage:
    return LocalFileStorage(get_settings().upload_dir)


def add_document(
    data: bytes,
    *,
    title: str = "Póliza de prueba",
    lineage_id: uuid.UUID | None = None,
    version: int = 1,
    status: DocumentStatus = DocumentStatus.PENDING,
    attempts: int = 0,
    store_file: bool = True,
) -> uuid.UUID:
    document_id = uuid.uuid4()
    if store_file:
        storage().save(document_id, io.BytesIO(data))
    with Session(get_sync_engine()) as session, session.begin():
        session.add(
            Document(
                id=document_id,
                lineage_id=lineage_id or document_id,
                version=version,
                title=title,
                filename="poliza.pdf",
                # unique per row, even when a test stores the same bytes twice
                content_sha256=hashlib.sha256(data + document_id.bytes).hexdigest(),
                size_bytes=len(data),
                status=status,
                attempts=attempts,
                progress=0,
            )
        )
    return document_id


def load(document_id: uuid.UUID) -> Document:
    with Session(get_sync_engine()) as session:
        return session.get_one(Document, document_id)


def chunks_of(document_id: uuid.UUID) -> list[Chunk]:
    with Session(get_sync_engine()) as session:
        return list(
            session.scalars(
                select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)
            )
        )


def wait_for(document_id: uuid.UUID, *statuses: DocumentStatus, timeout: float = 30) -> Document:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        document = load(document_id)
        if document.status in statuses:
            return document
        time.sleep(0.2)
    raise AssertionError(f"document stayed {load(document_id).status}, expected {statuses}")
