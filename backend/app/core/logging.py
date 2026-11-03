"""Structured JSON logging (structlog), correlated with OpenTelemetry traces.

Every log line carries `trace_id`/`span_id` when emitted inside a span, so a line from the
worker can be matched with the trace of the request that triggered it. Library loggers
(uvicorn, celery, sqlalchemy) go through the same pipeline.

Policy content, questions, prompts and secrets must never be logged. Callers log ids,
counts and lengths; `redact_sensitive` is a second line of defence for known-dangerous keys.
"""

import logging
import sys
from typing import Any

import structlog
from opentelemetry import trace

SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "password",
        "secret",
        "token",
        "content",
        "text",
        "question",
        "prompt",
        "answer",
        "quote",
    }
)


def add_trace_context(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


def redact_sensitive(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in event_dict:
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = "[REDACTED]"
    return event_dict


class _SkipHealthProbes(logging.Filter):
    """Docker probes /health/* every few seconds: not worth a log line each time."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/health/" not in str(record.args)


def configure_logging(*, service: str, level: str = "INFO", json: bool = True) -> None:
    def add_service(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event_dict.setdefault("service", service)
        return event_dict

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_service,
        add_trace_context,
        redact_sensitive,
    ]
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )
    handler = _StructuredHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Replace only our own handler (idempotent), never handlers installed by others.
    root.handlers = [h for h in root.handlers if not isinstance(h, _StructuredHandler)]
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Uvicorn installs its own non-propagating handlers: route it through the same pipeline,
    # so access logs are JSON and carry the trace id too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _SkipHealthProbes) for f in access.filters):
        access.addFilter(_SkipHealthProbes())
    # Chatty libraries: keep their warnings, drop their debug/info noise.
    for name in ("httpx", "httpcore", "LiteLLM", "litellm", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)


class _StructuredHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Marker type, so reconfiguring replaces exactly the handler installed here."""


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
