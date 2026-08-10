"""Read the approved Word register for the development-only administrator preview."""

from __future__ import annotations

from pathlib import Path

from docx import Document

from app.internal_preview import PreviewApplicantMetric


_HEADERS = (
    "Applicant",
    "Degree",
    "Age",
    "Academic age (years)",
    "Gender",
    "First-author papers",
    "Last-author papers",
    "Total papers",
    "h-index",
    "Total citations",
    "ORCID",
    "Google Scholar citations",
    "GS identity certainty",
)


def load_preview_register(path: Path) -> tuple[PreviewApplicantMetric, ...]:
    """Return source observations without changing the register or guessing values."""
    if not path.is_file():
        return ()
    try:
        document = Document(path)
    except (OSError, ValueError):
        return ()
    for table in document.tables:
        if not table.rows:
            continue
        headers = tuple(_text(cell.text) or "" for cell in table.rows[0].cells)
        if headers != _HEADERS:
            continue
        records: list[PreviewApplicantMetric] = []
        for row in table.rows[1:]:
            values = [_text(cell.text) for cell in row.cells]
            if len(values) != len(_HEADERS) or not values[0]:
                continue
            records.append(
                PreviewApplicantMetric(
                    applicant=values[0],
                    degree=values[1],
                    age=_float(values[2]),
                    academic_age=_float(values[3]),
                    gender=values[4],
                    first_author_papers=_integer(values[5]),
                    last_author_papers=_integer(values[6]),
                    total_papers=_integer(values[7]),
                    h_index=_integer(values[8]),
                    total_citations=_integer(values[9]),
                    orcid=values[10],
                    google_scholar_citations=_integer(values[11]),
                    identity_certainty=values[12],
                )
            )
        return tuple(records)
    return ()


def _text(value: str) -> str | None:
    normalized = " ".join(value.split())
    return normalized or None


def _integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = float(value.replace(",", ""))
    except ValueError:
        return None
    return int(parsed) if parsed.is_integer() and parsed >= 0 else None


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value.replace(",", ""))
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
