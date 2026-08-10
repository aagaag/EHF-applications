"""Strict parser for the approved 2026 Word applicant register."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from docx import Document


class RegisterParseError(ValueError):
    """Raised when the register cannot be imported without guessing."""


@dataclass(frozen=True, slots=True)
class RegisterApplicant:
    """One row of source observations from the Word register."""

    applicant_name: str
    degree: str | None
    age_observation: int | None
    academic_age_observation: float | None
    gender: str | None
    first_author_papers: int | None
    last_author_papers: int | None
    total_papers: int | None
    h_index: int | None
    total_citations: int | None
    orcid: str | None
    google_scholar_citations: int | None
    identity_certainty: str | None
    total_citations_qualifier: str | None = None


_COLUMNS = (
    "applicant",
    "degree",
    "age",
    "academicageyears",
    "gender",
    "firstauthorpapers",
    "lastauthorpapers",
    "totalpapers",
    "hindex",
    "totalcitations",
    "orcid",
    "googlescholarcitations",
    "gsidentitycertainty",
)
_ORCID = re.compile(r"^(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-[\dX]{4})$", re.IGNORECASE)


def parse_register(register_path: Path, *, expected_count: int = 36) -> tuple[RegisterApplicant, ...]:
    """Read the first Word table whose normalized headers match the approved register topology."""
    try:
        document = Document(register_path)
    except Exception as error:
        raise RegisterParseError("could not read Word register") from error

    table = next(
        (
            candidate
            for candidate in document.tables
            if candidate.rows
            and tuple(_normalized_header(cell.text) for cell in candidate.rows[0].cells) == _COLUMNS
        ),
        None,
    )
    if table is None:
        raise RegisterParseError("no table has the approved register header")

    applicants = tuple(_parse_row(row.cells, index) for index, row in enumerate(table.rows[1:], start=2))
    if len(applicants) != expected_count:
        raise RegisterParseError(
            f"register has {len(applicants)} applicant rows; expected {expected_count}"
        )
    return applicants


def _parse_row(cells: tuple[object, ...], row_number: int) -> RegisterApplicant:
    values = tuple(_optional_text(cell.text) for cell in cells)  # type: ignore[attr-defined]
    if len(values) != len(_COLUMNS):
        raise RegisterParseError(f"row {row_number} does not match the approved register columns")
    applicant_name = values[0]
    if applicant_name is None:
        raise RegisterParseError(f"row {row_number} applicant is required")
    total_citations, total_citations_qualifier = _citation_observation(
        values[9], row_number
    )
    return RegisterApplicant(
        applicant_name=applicant_name,
        degree=values[1],
        age_observation=_integer(values[2], "age", row_number),
        academic_age_observation=_number(values[3], "academic age", row_number),
        gender=values[4],
        first_author_papers=_integer(values[5], "first-author papers", row_number),
        last_author_papers=_integer(values[6], "last-author papers", row_number),
        total_papers=_integer(values[7], "total papers", row_number),
        h_index=_integer(values[8], "h-index", row_number),
        total_citations=total_citations,
        orcid=_orcid(values[10], row_number),
        google_scholar_citations=_integer(
            values[11], "Google Scholar citations", row_number
        ),
        identity_certainty=values[12],
        total_citations_qualifier=total_citations_qualifier,
    )


def _normalized_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _optional_text(value: str) -> str | None:
    normalized = value.strip()
    return normalized or None


def _integer(value: str | None, label: str, row_number: int) -> int | None:
    if _is_missing(value):
        return None
    assert value is not None
    if not re.fullmatch(r"[0-9]+", value):
        raise RegisterParseError(f"row {row_number} {label} must be an integer")
    return int(value)


def _orcid(value: str | None, row_number: int) -> str | None:
    if _is_missing(value):
        return None
    assert value is not None
    match = _ORCID.fullmatch(value)
    if match is None:
        raise RegisterParseError(f"row {row_number} ORCID is invalid")
    return match.group(1).upper()


def _number(value: str | None, label: str, row_number: int) -> float | None:
    if _is_missing(value):
        return None
    assert value is not None
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
        raise RegisterParseError(f"row {row_number} {label} must be a non-negative number")
    return float(value)


def _citation_observation(value: str | None, row_number: int) -> tuple[int | None, str | None]:
    if _is_missing(value):
        return None, None
    assert value is not None
    if re.fullmatch(r"[0-9]+", value):
        return int(value), None
    if re.fullmatch(r">[0-9]+", value):
        return None, value
    raise RegisterParseError(f"row {row_number} total citations must be an integer or lower bound")


def _is_missing(value: str | None) -> bool:
    return value is None or value.casefold() in {
        "nr",
        "n/r",
        "not reported",
        "not recorded",
        "not stated",
        "n/a",
    }
