"""Fresh PDF package construction for allowlisted application documents."""

from __future__ import annotations

import io
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject


class PdfPackageError(RuntimeError):
    """The selected document set cannot form a safe package."""


_UNSAFE_PDF_KEYS = tuple(
    NameObject(key)
    for key in (
        "/A",
        "/AA",
        "/AF",
        "/Annots",
        "/EmbeddedFiles",
        "/JavaScript",
        "/JS",
        "/Metadata",
        "/Names",
        "/OpenAction",
    )
)


def remove_unsafe_pdf_entries(value: Any, seen: set[tuple[object, ...]]) -> None:
    """Remove active or identifying objects before pypdf clones a page graph."""
    if isinstance(value, IndirectObject):
        marker = ("indirect", id(value.pdf), value.idnum, value.generation)
        if marker in seen:
            return
        seen.add(marker)
        value = value.get_object()
    marker = ("direct", id(value))
    if marker in seen:
        return
    seen.add(marker)
    if isinstance(value, DictionaryObject):
        for key in _UNSAFE_PDF_KEYS:
            value.pop(key, None)
        for key, nested in tuple(value.items()):
            if key != "/Parent":
                remove_unsafe_pdf_entries(nested, seen)
    elif isinstance(value, ArrayObject):
        for nested in tuple(value):
            remove_unsafe_pdf_entries(nested, seen)


def build_pdf_package(sources: tuple[bytes, ...]) -> bytes:
    if not sources:
        raise PdfPackageError("The application document package is unavailable.")
    writer = PdfWriter()
    try:
        for source in sources:
            reader = PdfReader(io.BytesIO(source), strict=True)
            if reader.is_encrypted or not reader.pages:
                raise PdfPackageError("The application document package is unavailable.")
            for page in reader.pages:
                remove_unsafe_pdf_entries(page, set())
                writer.add_page(page, excluded_keys=_UNSAFE_PDF_KEYS)
        writer.add_metadata(
            {
                "/Title": "EHF application document package",
                "/Author": "Ernst Hadorn Foundation",
                "/Subject": "Approved applicant-visible submitted documents",
                "/Creator": "EHF Fellowships",
            }
        )
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()
    except PdfPackageError:
        raise
    except Exception:
        raise PdfPackageError("The application document package is unavailable.") from None
