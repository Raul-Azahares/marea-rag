"""Document endpoints: upload, versions, status, retry, original file."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import DocumentServiceDep, StorageDep
from app.core.errors import ErrorCode, NotFoundError
from app.schemas.common import ErrorResponse
from app.schemas.documents import DocumentListOut, DocumentOut, DocumentUploadOut
from app.services.documents import UploadResult

router = APIRouter(prefix="/documents", tags=["documents"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}
_UPLOAD_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"model": DocumentUploadOut, "description": "Identical file already uploaded."},
    400: {"model": ErrorResponse, "description": "Empty file."},
    413: {"model": ErrorResponse, "description": "File too large."},
    415: {"model": ErrorResponse, "description": "Not a PDF."},
}

PdfFile = Annotated[UploadFile, File(description="Policy document (PDF).")]
Title = Annotated[str | None, Form(max_length=300, description="Optional display title.")]


def _to_upload_out(result: UploadResult, response: Response) -> DocumentUploadOut:
    if result.deduplicated:
        response.status_code = status.HTTP_200_OK
    response.headers["Location"] = f"/api/v1/documents/{result.document.id}"
    return DocumentUploadOut(
        **DocumentOut.model_validate(result.document).model_dump(),
        deduplicated=result.deduplicated,
        queued=result.queued,
    )


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentUploadOut,
    responses=_UPLOAD_RESPONSES,
)
async def upload_document(
    response: Response, service: DocumentServiceDep, file: PdfFile, title: Title = None
) -> DocumentUploadOut:
    """Upload a PDF and enqueue its ingestion. Returns immediately (202) with the document
    id; poll `GET /documents/{id}` for progress. Uploading the same bytes again is a no-op
    (200, `deduplicated: true`)."""
    result = await service.upload(
        file=file.file, filename=file.filename, content_type=file.content_type, title=title
    )
    return _to_upload_out(result, response)


@router.post(
    "/{document_id}/versions",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentUploadOut,
    responses={**_UPLOAD_RESPONSES, **_NOT_FOUND},
)
async def upload_new_version(
    document_id: uuid.UUID,
    response: Response,
    service: DocumentServiceDep,
    file: PdfFile,
    title: Title = None,
) -> DocumentUploadOut:
    """Upload a new version of an existing document. It replaces the current version only
    once its ingestion succeeds; older versions remain available for past citations."""
    result = await service.upload(
        file=file.file,
        filename=file.filename,
        content_type=file.content_type,
        title=title,
        parent_id=document_id,
    )
    return _to_upload_out(result, response)


@router.get("", response_model=DocumentListOut)
async def list_documents(
    service: DocumentServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListOut:
    documents, total = await service.list(limit=limit, offset=offset)
    return DocumentListOut(items=[DocumentOut.model_validate(d) for d in documents], total=total)


@router.get("/{document_id}", response_model=DocumentOut, responses=_NOT_FOUND)
async def get_document(document_id: uuid.UUID, service: DocumentServiceDep) -> DocumentOut:
    return DocumentOut.model_validate(await service.get(document_id))


@router.post(
    "/{document_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentUploadOut,
    responses={**_NOT_FOUND, 409: {"model": ErrorResponse, "description": "Not failed."}},
)
async def retry_document(
    document_id: uuid.UUID, response: Response, service: DocumentServiceDep
) -> DocumentUploadOut:
    """Re-enqueue a failed document (resets its attempt counter)."""
    return _to_upload_out(await service.retry(document_id), response)


@router.get(
    "/{document_id}/file",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}}, **_NOT_FOUND},
)
async def download_document_file(
    document_id: uuid.UUID, service: DocumentServiceDep, storage: StorageDep
) -> FileResponse:
    """The original PDF, served inline so the browser can open it at the cited page."""
    document = await service.get(document_id)
    if not storage.exists(document.id):
        raise NotFoundError(ErrorCode.FILE_MISSING, "El archivo original no está disponible.")
    return FileResponse(
        storage.path_for(document.id),
        media_type="application/pdf",
        filename=document.filename,
        content_disposition_type="inline",
    )
