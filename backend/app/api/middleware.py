"""Pure ASGI middlewares (no BaseHTTPMiddleware: no body buffering, streaming-safe)."""

import json

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import ErrorCode
from app.core.telemetry import current_trace_id


class _BodyTooLargeError(Exception):
    pass


class MaxBodySizeMiddleware:
    """Reject request bodies larger than `max_bytes` with 413, before they are buffered.

    Starlette parses the whole multipart body, spooling files to disk, *before* the endpoint
    runs, so a size check inside the endpoint would come too late. This middleware checks the
    declared Content-Length up front, and also counts the bytes actually received: a client can
    lie about or omit Content-Length (chunked encoding). nginx enforces the same limit at the
    edge; this is defence in depth for direct access to the API port.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _declared_content_length(scope)
        if declared is not None and declared > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        exceeded = False
        rejected = False

        async def guarded_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    raise _BodyTooLargeError
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal rejected
            # FastAPI turns the aborted body parse into its own 400; replace it with a 413.
            if exceeded:
                if message["type"] == "http.response.start" and not rejected:
                    rejected = True
                    await self._reject(send)
                return
            await send(message)

        try:
            await self.app(scope, guarded_receive, guarded_send)
        except _BodyTooLargeError:
            if not rejected:
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body: dict[str, object] = {
            "error": {
                "code": ErrorCode.FILE_TOO_LARGE,
                "message": f"La petición supera el tamaño máximo ({self.max_bytes // 2**20} MB).",
            }
        }
        if trace_id := current_trace_id():
            body["trace_id"] = trace_id
        payload = json.dumps(body).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})


class TraceIdHeaderMiddleware:
    """Expose the trace id of every request as `X-Trace-Id`, for support and for the UI."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_trace_id(message: Message) -> None:
            if message["type"] == "http.response.start" and (trace_id := current_trace_id()):
                MutableHeaders(scope=message).append("X-Trace-Id", trace_id)
            await send(message)

        await self.app(scope, receive, send_with_trace_id)


def _declared_content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
