from __future__ import annotations

import io

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject

from app.documents.extract import PdfExtractError, PdfSegment, build_pdf_extract


def _pdf(*widths: float, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for width in widths:
        page = writer.add_blank_page(width=width, height=100)
        page[NameObject("/AA")] = DictionaryObject(
            {NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("alert(1)")}
        )
    writer.add_metadata({"/Title": "Source title", "/Author": "Source author"})
    if encrypted:
        writer.encrypt("secret")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_extract_preserves_declared_segment_order_and_replaces_metadata() -> None:
    """Break caught: extraction could reorder ranges or retain applicant-identifying metadata."""
    source = _pdf(101, 202, 303, 404)

    payload = build_pdf_extract(
        (
            PdfSegment(source, 3, 4),
            PdfSegment(source, 1, 1),
        ),
        title="EHF fellowship application",
        subject="Reviewed application extract",
    )

    reader = PdfReader(io.BytesIO(payload), strict=True)
    assert [float(page.mediabox.width) for page in reader.pages] == [303, 404, 101]
    assert reader.metadata.title == "EHF fellowship application"
    assert reader.metadata.subject == "Reviewed application extract"
    assert reader.metadata.author == "Ernst Hadorn Foundation"
    assert "Source author" not in str(reader.metadata)
    assert all("/AA" not in page and "/JS" not in page for page in reader.pages)


@pytest.mark.parametrize(
    "segments",
    (
        (),
        (PdfSegment(_pdf(100), 0, 1),),
        (PdfSegment(_pdf(100), 1, 2),),
        (PdfSegment(_pdf(100), 2, 1),),
        (PdfSegment(b"not a pdf", 1, 1),),
        (PdfSegment(_pdf(100, encrypted=True), 1, 1),),
    ),
)
def test_extract_rejects_empty_invalid_out_of_bounds_and_encrypted_sources(
    segments: tuple[PdfSegment, ...],
) -> None:
    """Break caught: a malformed range or protected source could produce a partial review artifact."""
    with pytest.raises(PdfExtractError, match="unavailable"):
        build_pdf_extract(segments, title="Title", subject="Subject")
