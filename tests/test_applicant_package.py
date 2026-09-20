from __future__ import annotations

import io

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from app.documents.package import PdfPackageError, build_pdf_package


def _source_pdf(
    title: str,
    *,
    javascript: bool = False,
    attachment: bool = False,
    page_metadata: bool = False,
) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=72, height=72)
    if page_metadata:
        metadata = DecodedStreamObject()
        metadata.set_data(b"CONFIDENTIAL_METADATA_SENTINEL")
        page[NameObject("/Metadata")] = writer._add_object(metadata)
    writer.add_metadata({"/Title": title, "/Author": "Applicant source metadata"})
    if javascript:
        writer.add_js("app.alert('source action')")
    if attachment:
        writer.add_attachment("hidden-source-name.txt", b"source attachment")
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_package_rebuilds_allowlisted_pages_without_source_metadata_or_actions() -> None:
    """Break caught: a combined dossier could preserve names, attachments, or active actions."""
    payload = build_pdf_package(
        (
            _source_pdf(
                "private-cv-filename", javascript=True, page_metadata=True
            ),
            _source_pdf("private-plan-filename", attachment=True),
        )
    )

    reader = PdfReader(io.BytesIO(payload), strict=True)
    assert len(reader.pages) == 2
    assert reader.metadata.title == "EHF application document package"
    assert reader.metadata.author == "Ernst Hadorn Foundation"
    assert "private-cv-filename" not in repr(reader.metadata)
    assert "private-plan-filename" not in repr(reader.metadata)
    assert "/Names" not in reader.trailer["/Root"]
    assert "/OpenAction" not in reader.trailer["/Root"]
    assert b"CONFIDENTIAL_METADATA_SENTINEL" not in payload
    assert all("/Metadata" not in page for page in reader.pages)


@pytest.mark.parametrize("sources", ((), (b"not a pdf",)))
def test_package_refuses_empty_or_invalid_source_sets(sources: tuple[bytes, ...]) -> None:
    """Break caught: the package endpoint could emit a misleading empty or malformed PDF."""
    with pytest.raises(PdfPackageError):
        build_pdf_package(sources)
