import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DocumentStatus, IngestionStage


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lineage_id: uuid.UUID = Field(description="Shared by every version of the same document.")
    version: int
    title: str
    filename: str
    size_bytes: int
    page_count: int | None
    status: DocumentStatus
    stage: IngestionStage | None = Field(description="Current step while `processing`.")
    progress: int = Field(ge=0, le=100)
    error_code: str | None
    error_message: str | None
    chunk_count: int | None
    ingest_trace_id: str | None = Field(description="Trace of the last ingestion run (Jaeger).")
    superseded: bool = Field(description="True once a newer version is ready.")
    superseded_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None


class DocumentUploadOut(DocumentOut):
    deduplicated: bool = Field(
        description="True if this exact file already existed: no new ingestion was started."
    )
    queued: bool = Field(
        description=(
            "Whether an ingestion job was published. False for a new document means the "
            "broker was unreachable: the document stays `pending` and is enqueued automatically "
            "when the broker recovers."
        )
    )


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    total: int
