"""Synthetic PDF admission tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.documents.validation import PDFPolicy, PdfValidationError, validate_pdf


def pdf_bytes(*, pages: int = 1, encrypted: bool = False, attachment: bool = False, javascript: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if attachment:
        writer.add_attachment("synthetic.txt", b"synthetic attachment")
    if javascript:
        writer.add_js("app.alert('synthetic')")
    if encrypted:
        writer.encrypt("synthetic-password")
    destination = Path.cwd() / ".unused"
    import io

    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def write_pdf(tmp_path: Path, payload: bytes, name: str = "document.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def test_accepts_a_bounded_plain_pdf(tmp_path: Path) -> None:
    """Break caught: a safe, ordinary PDF could be rejected by the admission boundary."""
    source = write_pdf(tmp_path, pdf_bytes())

    admitted = validate_pdf(source, declared_filename="document.pdf", declared_media_type="application/pdf")

    assert admitted.page_count == 1
    assert admitted.media_type == "application/pdf"


def test_accepts_valid_pdf_bytes_from_a_private_tmp_quarantine_name(tmp_path: Path) -> None:
    """Break caught: every upload was rejected after its safe copy received a random .tmp name."""
    source = tmp_path / "private-quarantine.tmp"
    source.write_bytes(pdf_bytes())

    admitted = validate_pdf(
        source,
        declared_filename="document.pdf",
        declared_media_type="application/pdf",
    )

    assert admitted.page_count == 1


@pytest.mark.parametrize(
    ("filename", "media_type"),
    [("document.txt", "application/pdf"), ("document.pdf", "text/plain")],
)
def test_rejects_extension_or_media_type_mismatch(tmp_path: Path, filename: str, media_type: str) -> None:
    """Break caught: a non-PDF declared type could bypass the PDF-only admission boundary."""
    source = write_pdf(tmp_path, pdf_bytes())

    with pytest.raises(PdfValidationError):
        validate_pdf(source, declared_filename=filename, declared_media_type=media_type)


@pytest.mark.parametrize(
    "payload",
    [b"not a PDF", b"%PDF-1.7\nxref\n0 1\n0000000000 65535 f\ntrailer\n<< /Size 1 >>\n"],
)
def test_rejects_non_pdf_and_malformed_cross_reference_data(tmp_path: Path, payload: bytes) -> None:
    """Break caught: malformed bytes could reach the encrypted object store as a PDF."""
    source = write_pdf(tmp_path, payload)

    with pytest.raises(PdfValidationError):
        validate_pdf(source, declared_filename="document.pdf", declared_media_type="application/pdf")


@pytest.mark.parametrize(
    "kind",
    ["encrypted", "attachment", "javascript"],
)
def test_rejects_password_protection_embedded_files_and_active_content(tmp_path: Path, kind: str) -> None:
    """Break caught: a PDF with hidden or active material could be accepted for download."""
    source = write_pdf(
        tmp_path,
        pdf_bytes(
            encrypted=kind == "encrypted",
            attachment=kind == "attachment",
            javascript=kind == "javascript",
        ),
    )

    with pytest.raises(PdfValidationError):
        validate_pdf(source, declared_filename="document.pdf", declared_media_type="application/pdf")


def test_rejects_excessive_byte_and_page_limits(tmp_path: Path) -> None:
    """Break caught: unbounded PDFs could exhaust the importer or document worker."""
    source = write_pdf(tmp_path, pdf_bytes(pages=2))

    with pytest.raises(PdfValidationError):
        validate_pdf(source, declared_filename="document.pdf", declared_media_type="application/pdf", policy=PDFPolicy(max_bytes=1, max_pages=10))
    with pytest.raises(PdfValidationError):
        validate_pdf(source, declared_filename="document.pdf", declared_media_type="application/pdf", policy=PDFPolicy(max_bytes=1_000_000, max_pages=1))
