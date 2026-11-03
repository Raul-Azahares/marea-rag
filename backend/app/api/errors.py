"""Uniform error responses: `{"error": {"code", "message", "details?"}, "trace_id"}`.

The trace id lets a user report an error and an operator jump straight to its trace.
Error bodies never echo request input: it may contain policy text.
"""

from collections.abc import Mapping
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.telemetry import current_trace_id

logger = get_logger(__name__)


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    body: dict[str, Any] = {"error": error}
    if trace_id := current_trace_id():
        body["trace_id"] = trace_id
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body), headers=headers)


# Starlette dispatches each handler only for its registered exception type; `cast` just tells
# the type checker so.
async def _handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    error = cast(AppError, exc)
    return error_response(error.status_code, error.code, error.message)


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    error = cast(StarletteHTTPException, exc)
    return error_response(
        error.status_code, f"HTTP_{error.status_code}", str(error.detail), headers=error.headers
    )


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    error = cast(RequestValidationError, exc)
    details = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
        for err in error.errors()
    ]
    return error_response(
        422, ErrorCode.VALIDATION_ERROR, "La petición no es válida.", details=details
    )


async def _handle_database_unavailable(_: Request, exc: Exception) -> JSONResponse:
    logger.error("database_unavailable", error_type=type(exc).__name__)
    return error_response(
        503,
        ErrorCode.DATABASE_UNAVAILABLE,
        "La base de datos no está disponible. Inténtalo de nuevo en unos segundos.",
        headers={"Retry-After": "5"},
    )


async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error", error_type=type(exc).__name__)
    return error_response(
        500,
        ErrorCode.INTERNAL_ERROR,
        "Error interno. Si persiste, comparte el trace_id con soporte.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    for db_error in (OperationalError, InterfaceError, PoolTimeoutError):
        app.add_exception_handler(db_error, _handle_database_unavailable)
    app.add_exception_handler(Exception, _handle_unexpected)
