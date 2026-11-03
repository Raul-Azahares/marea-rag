from opentelemetry import trace

from app.core.logging import add_trace_context, redact_sensitive

tracer = trace.get_tracer(__name__)


def test_log_lines_carry_the_active_trace_and_span() -> None:
    with tracer.start_as_current_span("unit-test") as span:
        event = add_trace_context(None, "info", {"event": "something_happened"})

    context = span.get_span_context()
    assert event["trace_id"] == format(context.trace_id, "032x")
    assert event["span_id"] == format(context.span_id, "016x")


def test_no_trace_fields_outside_a_span() -> None:
    assert "trace_id" not in add_trace_context(None, "info", {"event": "x"})


def test_sensitive_keys_are_redacted_as_a_second_line_of_defence() -> None:
    event = redact_sensitive(
        None,
        "info",
        {"event": "x", "question": "¿cubre…?", "API_KEY": "secret", "document_id": "d1"},
    )

    assert event["question"] == "[REDACTED]"
    assert event["API_KEY"] == "[REDACTED]"
    assert event["document_id"] == "d1"
