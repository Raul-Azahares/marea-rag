"""OpenTelemetry helpers shared by the API and the worker."""

from opentelemetry import trace


def current_trace_id() -> str | None:
    """Hex trace id of the active span, if any (used in responses and logs)."""
    span_context = trace.get_current_span().get_span_context()
    return format(span_context.trace_id, "032x") if span_context.is_valid else None
