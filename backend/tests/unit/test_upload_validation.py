import hashlib
import io
from collections.abc import Callable

import pytest

from app.core.errors import (
    AppError,
    ErrorCode,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from app.ingestion.upload_validation import (
    InspectedUpload,
    default_title,
    inspect_pdf_upload,
    sanitize_filename,
)

MB = 1024 * 1024


def inspect(
    data: bytes,
    *,
    filename: str = "poliza.pdf",
    content_type: str | None = "application/pdf",
    max_bytes: int = MB,
) -> InspectedUpload:
    return inspect_pdf_upload(
        io.BytesIO(data), filename=filename, content_type=content_type, max_bytes=max_bytes
    )


def test_valid_pdf_is_hashed_and_rewound(make_blank_pdf: Callable[[], bytes]) -> None:
    data = make_blank_pdf()
    file = io.BytesIO(data)

    result = inspect_pdf_upload(
        file, filename="Poliza.PDF", content_type="application/pdf", max_bytes=MB
    )

    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert result.size_bytes == len(data)
    assert file.tell() == 0  # ready to be stored


def test_empty_file_is_rejected() -> None:
    with pytest.raises(AppError) as excinfo:
        inspect(b"")
    assert excinfo.value.code is ErrorCode.EMPTY_FILE
    assert excinfo.value.status_code == 400


@pytest.mark.parametrize("filename", ["poliza.docx", "poliza", "poliza.pdf.exe", None])
def test_non_pdf_extension_is_rejected(filename: str | None) -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        inspect_pdf_upload(
            io.BytesIO(b"%PDF-1.7 ..."), filename=filename, content_type=None, max_bytes=MB
        )


def test_magic_bytes_win_over_a_spoofed_extension() -> None:
    with pytest.raises(UnsupportedMediaTypeError) as excinfo:
        inspect(b"<html>not a pdf</html>", filename="malware.pdf")
    assert excinfo.value.code is ErrorCode.UNSUPPORTED_MEDIA_TYPE


def test_unexpected_declared_content_type_is_rejected() -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        inspect(b"%PDF-1.7 ...", content_type="text/html")


@pytest.mark.parametrize(
    "content_type", ["application/pdf", "application/octet-stream", "application/pdf; x=y", None]
)
def test_accepted_content_types(content_type: str | None) -> None:
    assert inspect(b"%PDF-1.7 minimal", content_type=content_type).size_bytes > 0


def test_header_after_leading_garbage_is_accepted() -> None:
    # The PDF spec tolerates bytes before the header within the first 1024 bytes.
    data = b"\x00" * 100 + b"%PDF-1.4 ..."
    assert inspect(data).size_bytes == len(data)


def test_file_over_the_limit_is_rejected() -> None:
    with pytest.raises(PayloadTooLargeError) as excinfo:
        inspect(b"%PDF-" + b"0" * (2 * MB), max_bytes=MB)
    assert excinfo.value.status_code == 413
    assert excinfo.value.code is ErrorCode.FILE_TOO_LARGE


def test_small_file_over_a_tiny_limit_is_rejected() -> None:
    with pytest.raises(PayloadTooLargeError):
        inspect(b"%PDF-" + b"0" * 500, max_bytes=100)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\ana\\poliza.pdf", "poliza.pdf"),
        ("poli\x00za\x1f.pdf", "poliza.pdf"),
        ("Póliza Hogar.pdf", "Póliza Hogar.pdf"),
        ("", "documento.pdf"),
        (None, "documento.pdf"),
    ],
)
def test_sanitize_filename(raw: str | None, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_default_title_from_filename() -> None:
    assert default_title("condicionado_hogar__2025.pdf") == "condicionado hogar 2025"
