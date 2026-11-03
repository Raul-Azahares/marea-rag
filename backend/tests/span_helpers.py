"""Helpers to inspect the spans captured by the in-memory exporter."""

import time
from collections.abc import Iterable

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def in_trace(exporter: InMemorySpanExporter, trace_id: int) -> list[ReadableSpan]:
    return [
        s for s in exporter.get_finished_spans() if s.context and s.context.trace_id == trace_id
    ]


def named(spans: Iterable[ReadableSpan], name: str) -> ReadableSpan:
    matches = [s for s in spans if s.name == name]
    assert len(matches) == 1, f"expected one span named {name!r}, got {len(matches)}"
    return matches[0]


def wait_for_span(
    exporter: InMemorySpanExporter, name: str, *, timeout: float = 10
) -> ReadableSpan:
    """Spans are exported when they *end*: a worker's span may still be open for a moment."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for span in exporter.get_finished_spans():
            if span.name == name:
                return span
        time.sleep(0.1)
    raise AssertionError(f"span {name!r} never finished")


def all_recorded_text(spans: Iterable[ReadableSpan]) -> str:
    """Everything a tracing backend would store: names, attributes, events, statuses."""
    parts: list[str] = []
    for span in spans:
        parts.append(span.name)
        parts.extend(f"{k}={v}" for k, v in (span.attributes or {}).items())
        for event in span.events:
            parts.append(event.name)
            parts.extend(f"{k}={v}" for k, v in (event.attributes or {}).items())
        if span.status.description:
            parts.append(span.status.description)
    return "\n".join(parts)
