"""Fail-closed PDF admission checks that preserve accepted PDF vectors."""

from __future__ import annotations

from dataclasses import dataclass
import contextlib
import io
from pathlib import Path
from typing import Any

from pypdf import PdfReader


class PdfValidationError(RuntimeError):
    """Raised without document names, paths, or parser diagnostics."""


@dataclass(frozen=True, slots=True)
class PDFPolicy:
    max_bytes: int = 25 * 1024 * 1024
    max_pages: int = 100


@dataclass(frozen=True, slots=True)
class ValidatedPdf:
    media_type: str
    page_count: int
    byte_size: int


def validate_pdf(
    source: Path,
    *,
    declared_filename: str,
    declared_media_type: str,
    policy: PDFPolicy = PDFPolicy(),
) -> ValidatedPdf:
    """Accept only bounded, ordinary PDFs without encrypted, embedded, or active content."""
    try:
        if policy.max_bytes <= 0 or policy.max_pages <= 0:
            raise ValueError
        # The bytes are validated from a private quarantine file whose random
        # staging name intentionally ends in .tmp. The user-visible declared
        # filename must still be PDF-only, while magic and structure checks
        # below remain authoritative for the staged content.
        if Path(declared_filename).suffix.casefold() != ".pdf":
            raise ValueError
        if declared_media_type.casefold() != "application/pdf":
            raise ValueError
        byte_size = source.stat().st_size
        if byte_size <= 0 or byte_size > policy.max_bytes:
            raise ValueError
        with source.open("rb") as stream:
            if stream.read(8)[:5] != b"%PDF-":
                raise ValueError
        # Legacy PDFs often contain repairable xref offsets. Tolerant structural
        # parsing is acceptable only because the independent active-content,
        # encryption, attachment, size, and page limits below still fail closed.
        with contextlib.redirect_stderr(io.StringIO()):
            reader = PdfReader(str(source), strict=False)
        if reader.is_encrypted:
            raise ValueError
        page_count = len(reader.pages)
        if page_count <= 0 or page_count > policy.max_pages:
            raise ValueError
        if _has_disallowed_content(reader.trailer["/Root"]):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise PdfValidationError("PDF admission failed.") from None
    except Exception:
        raise PdfValidationError("PDF admission failed.") from None
    return ValidatedPdf(media_type="application/pdf", page_count=page_count, byte_size=byte_size)


def _has_disallowed_content(value: Any, visited: set[int] | None = None) -> bool:
    """Walk the PDF object graph for attachments and every executable action entry."""
    if visited is None:
        visited = set()
    if hasattr(value, "get_object"):
        value = value.get_object()
    if isinstance(value, dict):
        marker = id(value)
        if marker in visited:
            return False
        visited.add(marker)
        keys = {str(key) for key in value}
        if keys & {"/EmbeddedFiles", "/JavaScript", "/JS", "/AA"}:
            return True
        action = str(value.get("/S", ""))
        if action in {"/JavaScript", "/Launch", "/SubmitForm", "/GoToR", "/RichMedia", "/Sound", "/Movie"}:
            return True
        return any(_has_disallowed_content(item, visited) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_disallowed_content(item, visited) for item in value)
    return False
