from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from starlette.types import Receive, Scope, Send

from app.api.middleware import MaxBodySizeMiddleware
from app.core.config import get_settings
from app.main import create_app


async def _echo_app(scope: Scope, receive: Receive, send: Send) -> None:
    """Reads the whole body, then answers 200 with its length."""
    size = 0
    while True:
        message = await receive()
        size += len(message.get("body", b""))
        if not message.get("more_body", False):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": str(size).encode()})


def _client(app: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]


async def test_body_within_the_limit_passes() -> None:
    async with _client(MaxBodySizeMiddleware(_echo_app, max_bytes=10)) as client:
        response = await client.post("/", content=b"x" * 10)
    assert response.status_code == 200
    assert response.text == "10"


async def test_declared_content_length_over_the_limit_is_rejected_upfront() -> None:
    async with _client(MaxBodySizeMiddleware(_echo_app, max_bytes=10)) as client:
        response = await client.post("/", content=b"x" * 11)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


async def test_chunked_body_without_content_length_is_cut_off() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(3):
            yield b"x" * 6

    async with _client(MaxBodySizeMiddleware(_echo_app, max_bytes=10)) as client:
        response = await client.post("/", content=chunks())
    assert response.status_code == 413


@pytest.fixture
def one_mb_upload_limit(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("one_mb_upload_limit")
async def test_oversized_chunked_multipart_upload_gets_413_not_fastapis_400() -> None:
    """Through the real app: FastAPI would turn the aborted multipart parse into a 400."""
    boundary = "marea-boundary"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="big.pdf"'
        "\r\nContent-Type: application/pdf\r\n\r\n"
    ).encode()

    async def body() -> AsyncIterator[bytes]:
        yield head
        for _ in range(40):  # ~4 MB > 1 MB limit + 1 MB multipart allowance
            yield b"%PDF-" + b"0" * 100_000
        yield f"\r\n--{boundary}--\r\n".encode()

    async with _client(create_app()) as client:
        response = await client.post(
            "/api/v1/documents",
            content=body(),
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
