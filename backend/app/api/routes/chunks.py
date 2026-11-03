"""Source-fragment viewer: lets the agent read exactly what a citation points to."""

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import SessionDep
from app.core.errors import ErrorCode, NotFoundError
from app.db.models import Chunk, Document
from app.schemas.common import ErrorResponse
from app.schemas.query import ChunkOut

router = APIRouter(prefix="/chunks", tags=["chunks"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}


@router.get("/{chunk_id}", response_model=ChunkOut, responses=_NOT_FOUND)
async def get_chunk(chunk_id: uuid.UUID, session: SessionDep) -> ChunkOut:
    """Superseded versions stay readable, so citations in past answers remain verifiable."""
    row = (
        await session.execute(
            # Explicit columns: the 768-float embedding is never needed here.
            select(
                Chunk.id,
                Chunk.section,
                Chunk.page_start,
                Chunk.page_end,
                Chunk.content,
                Chunk.flags,
                Document.id.label("document_id"),
                Document.title,
                Document.version,
                Document.superseded_at,
            )
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.id == chunk_id)
        )
    ).first()
    if row is None:
        raise NotFoundError(ErrorCode.CHUNK_NOT_FOUND, "El fragmento no existe.")
    return ChunkOut(
        id=row.id,
        document_id=row.document_id,
        document_title=row.title,
        document_version=row.version,
        document_superseded=row.superseded_at is not None,
        section=row.section,
        page_start=row.page_start,
        page_end=row.page_end,
        content=row.content,
        flags=list(row.flags or []),
    )
