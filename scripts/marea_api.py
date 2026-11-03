"""Tiny client for the Marea API, standard library only (shared by the scripts in this folder)."""

import json
import time
import urllib.error
import urllib.request
import uuid
from typing import Any


class ApiError(Exception):
    pass


def request(
    method: str, url: str, body: bytes | None = None, headers: dict[str, str] | None = None
) -> tuple[int, Any]:
    if not url.startswith(("http://", "https://")):  # urllib would also open file:// URLs
        raise ValueError(f"not an HTTP URL: {url}")
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=90) as response:  # noqa: S310 (checked above)
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


def upload_pdf(
    base_url: str,
    data: bytes,
    filename: str,
    *,
    title: str | None = None,
    new_version_of: str | None = None,
) -> dict[str, Any]:
    """POST a PDF as multipart/form-data; `new_version_of` uploads it as a new version."""
    boundary = uuid.uuid4().hex
    parts = b""
    if title:
        parts += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\n{title}\r\n'
        ).encode()
    parts += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    body = parts + data + f"\r\n--{boundary}--\r\n".encode()
    path = f"/documents/{new_version_of}/versions" if new_version_of else "/documents"
    status, payload = request(
        "POST",
        f"{base_url}/api/v1{path}",
        body,
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    if status not in (200, 202) or not isinstance(payload, dict):
        raise ApiError(f"upload of {filename} answered {status}: {payload}")
    return payload


def wait_until_ready(base_url: str, document_id: str, timeout_s: float = 180) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status, document = request("GET", f"{base_url}/api/v1/documents/{document_id}")
        if status == 200 and document["status"] == "ready":
            return dict(document)
        if status == 200 and document["status"] == "failed":
            raise ApiError(
                f"ingestion failed: {document['error_code']} {document['error_message']}"
            )
        time.sleep(1)
    raise ApiError(f"document {document_id} not ready after {timeout_s:.0f} s")
