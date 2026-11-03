"""OpenTelemetry for the API and the Celery worker.

Every process sends its traces over OTLP/HTTP (OTEL_EXPORTER_OTLP_ENDPOINT) to the collector,
which batches them and forwards them to Jaeger.

What is traced:
- FastAPI: one server span per request. Health probes and the ASGI send/receive internals are
  excluded as noise.
- Celery: a producer span when a task is published and a consumer span when it runs. The trace
  context travels in the message headers, so the background task is a child of the HTTP
  request that enqueued it.
- SQLAlchemy: one span per statement. Only the SQL text is recorded, never the bound values.
- Redis and HTTPX: broker commands and outgoing HTTP calls (LLM providers).
- Domain spans (ingest.*, rag.*) and a GenAI client span for every model call
  (app/providers/tracing.py).

Prompts, completions and document text are never recorded: content capture is off by design.
"""

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

_provider: TracerProvider | None = None


def current_trace_id() -> str | None:
    """Hex trace id of the active span, if any (used in responses and logs)."""
    span_context = trace.get_current_span().get_span_context()
    return format(span_context.trace_id, "032x") if span_context.is_valid else None


def init_tracing(
    service_name: str, *, environment: str, exporter: SpanExporter | None = None
) -> None:
    """Install the tracer provider and the library instrumentation, once per process.

    It must run in the process that produces the spans. In a Celery prefork worker that means
    each child, after the fork (see app.worker.signals), because the exporter's background
    thread does not survive fork(). Engines created afterwards are instrumented automatically.
    """
    global _provider
    if _provider is not None:
        return
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": service_name,
                "service.namespace": "marea",
                "service.version": "0.1.0",
                "deployment.environment.name": environment,
            }
        )
    )
    # Batched and exported in the background in production; synchronous for tests.
    processor = (
        SimpleSpanProcessor(exporter) if exporter else BatchSpanProcessor(OTLPSpanExporter())
    )
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    SQLAlchemyInstrumentor().instrument()
    RedisInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
    CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]  # package ships no type hints
    _provider = provider


def instrument_fastapi(app: FastAPI) -> None:
    FastAPIInstrumentor.instrument_app(
        app, excluded_urls="health/live,health/ready", exclude_spans=["receive", "send"]
    )


def flush_tracing() -> None:
    """Export whatever is still buffered. Needed where atexit hooks never run, such as a
    Celery prefork child, which exits through os._exit()."""
    if _provider is not None:
        _provider.force_flush(timeout_millis=5_000)
