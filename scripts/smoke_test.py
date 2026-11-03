#!/usr/bin/env python3
"""End-to-end smoke test against a running stack (`docker compose up --wait`).

What an evaluator does first, through the same door as the UI (nginx on :3000):
1. upload a freshly generated PDF (unique bytes, so it is always a new ingestion);
2. wait until the worker has processed it (Celery over Redis);
3. ask a question scoped to it and require a verified, cited answer;
4. find both traces in Jaeger: the upload spans the API and the worker (Celery) down to the
   embeddings call, and the question reaches the chat model.

Standard library only, so it runs on a bare CI runner:

    python3 scripts/smoke_test.py [--base-url URL] [--jaeger-url URL]
"""

import argparse
import json
import sys
import time
import urllib.error
import uuid
from typing import Any

from marea_api import ApiError, request, upload_pdf, wait_until_ready

QUESTION = "¿Hasta qué importe cubre la póliza de prueba los daños por humo?"


def make_pdf(lines: list[str]) -> bytes:
    """A minimal, valid one-page PDF with a real text layer (Helvetica, ASCII text)."""

    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    stream = "BT /F1 11 Tf 16 TL 72 760 Td "
    stream += " ".join(f"({escape(line)}) Tj T*" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    pdf += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    pdf += f"startxref\n{xref}\n%%EOF\n".encode()
    return bytes(pdf)


def ask(base_url: str, document_id: str) -> dict[str, Any]:
    body = json.dumps({"question": QUESTION, "document_ids": [document_id]}).encode()
    status, answer = request(
        "POST", f"{base_url}/api/v1/query", body, {"Content-Type": "application/json"}
    )
    if status != 200 or not isinstance(answer, dict):
        raise ApiError(f"query answered {status}: {answer}")
    citations = answer["citations"]
    if answer["status"] not in ("answered", "partial") or not citations:
        raise ApiError(f"no cited answer: status={answer['status']} answer={answer['answer']!r}")
    if any(c["document_id"] != document_id for c in citations):
        raise ApiError("a citation points outside the requested document")
    if not any("900 euros" in c["quote"] for c in citations):
        raise ApiError(f"the expected fact is not quoted: {[c['quote'] for c in citations]}")
    if not answer["validation"]["passed"]:
        raise ApiError(f"citation validation failed: {answer['validation']}")
    return answer


def wait_for_trace(
    jaeger_url: str,
    trace_id: str,
    services: set[str],
    span_prefixes: list[str],
    timeout_s: float = 60,
) -> tuple[set[str], int]:
    """Spans are exported in batches: poll until the trace holds everything expected."""
    deadline = time.monotonic() + timeout_s
    found_services: set[str] = set()
    names: set[str] = set()
    while time.monotonic() < deadline:
        status, payload = request("GET", f"{jaeger_url}/api/v3/traces/{trace_id}")
        if status == 200 and isinstance(payload, dict):
            resource_spans = payload["result"]["resourceSpans"]
            found_services = {
                attribute["value"]["stringValue"]
                for resource in resource_spans
                for attribute in resource["resource"]["attributes"]
                if attribute["key"] == "service.name"
            }
            names = {
                span["name"]
                for resource in resource_spans
                for scope in resource["scopeSpans"]
                for span in scope["spans"]
            }
            if services <= found_services and all(
                any(name.startswith(prefix) for name in names) for prefix in span_prefixes
            ):
                return found_services, len(names)
        time.sleep(2)
    missing = [p for p in span_prefixes if not any(n.startswith(p) for n in names)]
    raise ApiError(
        f"trace {trace_id} incomplete after {timeout_s:.0f} s: services={sorted(found_services)}, "
        f"missing spans={missing}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="http://localhost:3000", help="the UI (nginx)")
    parser.add_argument("--jaeger-url", default="http://localhost:16686")
    args = parser.parse_args()

    token = uuid.uuid4().hex[:12]
    pdf = make_pdf(
        [
            "Marea Seguros - Poliza de prueba automatica",
            "Articulo 1. Danos por humo",
            "La poliza de prueba cubre los danos por humo en la vivienda asegurada hasta "
            "900 euros por siniestro.",
            f"Referencia de la prueba: SMOKE-{token}.",
        ]
    )
    started = time.monotonic()
    try:
        document = upload_pdf(
            args.base_url, pdf, f"smoke-{token}.pdf", title=f"Prueba automatica {token}"
        )
        if document["deduplicated"] or not document["queued"]:
            raise ApiError(f"expected a new, queued document: {document}")
        print(f"✓ subida aceptada (202, en cola): documento {document['id']}")

        document = wait_until_ready(args.base_url, document["id"])
        print(f"✓ procesado por el worker: {document['chunk_count']} fragmento(s)")

        answer = ask(args.base_url, document["id"])
        print(f"✓ respuesta verificada ({answer['status']}, {len(answer['citations'])} cita(s))")

        services, spans = wait_for_trace(
            args.jaeger_url,
            document["ingest_trace_id"],
            {"marea-api", "marea-worker"},
            ["POST /api/v1/documents", "run/marea.ingest_document", "embeddings "],
        )
        print(f"✓ traza de la subida en Jaeger: {', '.join(sorted(services))} ({spans} spans)")

        services, spans = wait_for_trace(
            args.jaeger_url, answer["trace_id"], {"marea-api"}, ["POST /api/v1/query", "chat "]
        )
        print(f"✓ traza de la pregunta en Jaeger, con la llamada al LLM ({spans} spans)")
    except (ApiError, urllib.error.URLError, KeyError) as exc:
        print(f"✗ smoke test fallido: {exc!r}", file=sys.stderr)
        return 1
    print(f"Smoke test OK en {time.monotonic() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
