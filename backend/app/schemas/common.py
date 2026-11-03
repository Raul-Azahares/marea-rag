from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict[str, object]] | None = None


class ErrorResponse(BaseModel):
    """Body of every 4xx/5xx response."""

    error: ErrorDetail
    trace_id: str | None = None
