"""Build reviewed, page-bounded PDFs from immutable applicant sources."""

from __future__ import annotations

from dataclasses import dataclass
import io

from pypdf import PdfReader, PdfWriter

from app.documents.package import _UNSAFE_PDF_KEYS, remove_unsafe_pdf_entries


class PdfExtractError(RuntimeError):
    """A source or page range cannot form a safe reviewed artifact."""


@dataclass(frozen=True, slots=True)
class PdfSegment:
    payload: bytes
    first_page: int
    last_page: int


def build_pdf_extract(
    segments: tuple[PdfSegment, ...], *, title: str, subject: str
) -> bytes:
    """Return a sanitized PDF containing one-based inclusive ranges in order."""
    if not segments or not title.strip() or not subject.strip():
        raise PdfExtractError("The reviewed PDF extract is unavailable.")
    writer = PdfWriter()
    try:
        for segment in segments:
            reader = PdfReader(io.BytesIO(segment.payload), strict=True)
            if (
                reader.is_encrypted
                or not reader.pages
                or segment.first_page < 1
                or segment.last_page < segment.first_page
                or segment.last_page > len(reader.pages)
            ):
                raise PdfExtractError("The reviewed PDF extract is unavailable.")
            for page_number in range(segment.first_page - 1, segment.last_page):
                page = reader.pages[page_number]
                remove_unsafe_pdf_entries(page, set())
                writer.add_page(page, excluded_keys=_UNSAFE_PDF_KEYS)
        writer.add_metadata(
            {
                "/Title": title.strip(),
                "/Author": "Ernst Hadorn Foundation",
                "/Subject": subject.strip(),
                "/Creator": "EHF Fellowships",
            }
        )
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()
    except PdfExtractError:
        raise
    except Exception:
        raise PdfExtractError("The reviewed PDF extract is unavailable.") from None
