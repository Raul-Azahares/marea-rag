"""Small PDFs built on the fly for extraction and ingestion tests."""

import io

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas


def make_text_pdf(pages: list[str]) -> bytes:
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=1)
    for page in pages:
        text = canvas.beginText(2 * cm, 27 * cm)
        text.setFont("Helvetica", 10)
        for line in page.splitlines():
            text.textLine(line)
        canvas.drawText(text)
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def make_encrypted_pdf(text: str, *, user_password: str) -> bytes:
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(make_text_pdf([text]))))
    writer.encrypt(user_password=user_password, owner_password="owner-secret")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
