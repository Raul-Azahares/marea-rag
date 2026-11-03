"""Upload, deduplication, versioning, retry and failure handling through the HTTP API."""

import uuid
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.session import get_session, get_sync_engine
from tests.fakes import RecordingQueue

pytestmark = pytest.mark.integration


async def upload(
    client: httpx.AsyncClient,
    data: bytes,
    *,
    name: str = "poliza.pdf",
    url: str = "/api/v1/documents",
) -> httpx.Response:
    return await client.post(url, files={"file": (name, data, "application/pdf")})


def set_status(document_id: str, status: str) -> None:
    with get_sync_engine().begin() as connection:
        connection.execute(
            text(
                "UPDATE documents SET status = :s, attempts = 3, error_code = 'PDF_CORRUPT' "
                "WHERE id = :id"
            ),
            {"s": status, "id": document_id},
        )


async def test_upload_returns_202_and_enqueues_ingestion(
    client: httpx.AsyncClient, queue: RecordingQueue, make_blank_pdf: Callable[[], bytes]
) -> None:
    data = make_blank_pdf()

    response = await upload(client, data, name="condicionado_hogar.pdf")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["version"] == 1
    assert body["lineage_id"] == body["id"]
    assert body["title"] == "condicionado hogar"
    assert body["deduplicated"] is False
    assert body["queued"] is True
    assert response.headers["location"] == f"/api/v1/documents/{body['id']}"
    assert queue.enqueued == [uuid.UUID(body["id"])]
    stored = get_settings().upload_dir / f"{body['id']}.pdf"
    assert stored.read_bytes() == data


async def test_same_bytes_are_deduplicated(
    client: httpx.AsyncClient, queue: RecordingQueue, make_blank_pdf: Callable[[], bytes]
) -> None:
    data = make_blank_pdf()
    first = (await upload(client, data)).json()

    second = await upload(client, data, name="otro_nombre.pdf")

    assert second.status_code == 200
    assert second.json()["id"] == first["id"]
    assert second.json()["deduplicated"] is True
    assert second.json()["queued"] is False
    assert len(queue.enqueued) == 1  # no second ingestion


async def test_reuploading_a_failed_file_retries_it(
    client: httpx.AsyncClient, queue: RecordingQueue, make_blank_pdf: Callable[[], bytes]
) -> None:
    data = make_blank_pdf()
    document_id = (await upload(client, data)).json()["id"]
    set_status(document_id, "failed")

    response = await upload(client, data)

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["status"], body["error_code"]) == (document_id, "pending", None)
    assert body["queued"] is True
    assert len(queue.enqueued) == 2


async def test_broker_down_keeps_document_pending(
    client: httpx.AsyncClient, queue: RecordingQueue, make_blank_pdf: Callable[[], bytes]
) -> None:
    queue.available = False

    response = await upload(client, make_blank_pdf())

    assert response.status_code == 202  # accepted: the reconciler will enqueue it later
    assert response.json()["status"] == "pending"
    assert response.json()["queued"] is False


@pytest.mark.parametrize(
    ("data", "name", "status", "code"),
    [
        (b"", "vacio.pdf", 400, "EMPTY_FILE"),
        (b"just text", "notas.pdf", 415, "UNSUPPORTED_MEDIA_TYPE"),
        (b"%PDF-1.7", "poliza.docx", 415, "UNSUPPORTED_MEDIA_TYPE"),
    ],
)
async def test_invalid_uploads_are_rejected_and_nothing_is_stored(
    client: httpx.AsyncClient,
    queue: RecordingQueue,
    data: bytes,
    name: str,
    status: int,
    code: str,
) -> None:
    response = await upload(client, data, name=name)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert queue.enqueued == []
    assert (await client.get("/api/v1/documents")).json()["total"] == 0


async def test_new_version_joins_the_lineage(
    client: httpx.AsyncClient, make_blank_pdf: Callable[[], bytes]
) -> None:
    v1 = (await upload(client, make_blank_pdf(), name="hogar.pdf")).json()

    response = await upload(
        client,
        make_blank_pdf(),
        name="hogar_2026.pdf",
        url=f"/api/v1/documents/{v1['id']}/versions",
    )

    assert response.status_code == 202
    v2 = response.json()
    assert v2["lineage_id"] == v1["lineage_id"]
    assert v2["version"] == 2
    assert v2["title"] == v1["title"]  # inherited
    assert v2["superseded"] is False


async def test_new_version_of_unknown_document_is_404(
    client: httpx.AsyncClient, make_blank_pdf: Callable[[], bytes]
) -> None:
    response = await upload(
        client, make_blank_pdf(), url=f"/api/v1/documents/{uuid.uuid4()}/versions"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


async def test_list_and_get(client: httpx.AsyncClient, make_blank_pdf: Callable[[], bytes]) -> None:
    ids = [(await upload(client, make_blank_pdf())).json()["id"] for _ in range(3)]

    listing = (await client.get("/api/v1/documents", params={"limit": 2})).json()
    detail = await client.get(f"/api/v1/documents/{ids[0]}")

    assert listing["total"] == 3
    assert len(listing["items"]) == 2
    assert detail.status_code == 200
    assert detail.json()["id"] == ids[0]


async def test_unknown_document_is_404_with_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/v1/documents/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "DOCUMENT_NOT_FOUND",
        "message": "El documento no existe.",
    }


async def test_retry_only_accepts_failed_documents(
    client: httpx.AsyncClient, queue: RecordingQueue, make_blank_pdf: Callable[[], bytes]
) -> None:
    document_id = (await upload(client, make_blank_pdf())).json()["id"]

    conflict = await client.post(f"/api/v1/documents/{document_id}/retry")
    set_status(document_id, "failed")
    retried = await client.post(f"/api/v1/documents/{document_id}/retry")

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "INVALID_STATE"
    assert retried.status_code == 202
    assert retried.json()["status"] == "pending"
    assert len(queue.enqueued) == 2


async def test_original_file_is_served_inline(
    client: httpx.AsyncClient, make_blank_pdf: Callable[[], bytes]
) -> None:
    data = make_blank_pdf()
    document_id = (await upload(client, data, name="poliza.pdf")).json()["id"]

    response = await client.get(f"/api/v1/documents/{document_id}/file")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.content == data


async def test_database_down_returns_503(app: FastAPI, client: httpx.AsyncClient) -> None:
    unreachable = create_async_engine(
        "postgresql+psycopg://marea:marea@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    sessions = async_sessionmaker(unreachable)

    async def broken_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = broken_session
    try:
        response = await client.get("/api/v1/documents")
    finally:
        del app.dependency_overrides[get_session]
        await unreachable.dispose()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert response.headers["retry-after"] == "5"
