"""Canonical server-owned applicant field inventory and validation."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any
from urllib.parse import urlparse

from app.applicant.contribution import ContributionError, validate_contribution
from app.applicant.publications import InvalidDoi, normalize_doi


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    code: str
    section: str
    label: str
    kind: str
    required: bool = False
    help: str = ""
    options: tuple[str, ...] = ()


def _field(
    code: str,
    section: str,
    label: str,
    kind: str,
    required: bool = False,
    help: str = "",
    options: tuple[str, ...] = (),
) -> FieldDefinition:
    return FieldDefinition(code, section, label, kind, required, help, options)


FIELD_INVENTORY = (
    _field("fullName", "identity", "Full name", "text", True),
    _field("preferredName", "identity", "Preferred name", "text"),
    _field("registeredEmail", "identity", "Registered email address", "email", True),
    _field("alternativeEmail", "identity", "Alternative contact email", "email"),
    _field("telephone", "identity", "Telephone number", "text", True),
    _field("birthMonth", "identity", "Birth month", "integer", True),
    _field("birthYear", "identity", "Birth year", "integer", True),
    _field(
        "gender",
        "identity",
        "Gender (optional)",
        "choice",
        options=("Female", "Male", "Non-binary", "Prefer not to say"),
    ),
    _field("institute", "employment", "Current UZH institute or department", "text", True),
    _field("principalInvestigator", "employment", "Current principal investigator", "text", True),
    _field("positionTitle", "employment", "Current position title", "text", True),
    _field(
        "postdoctoralEmploymentStatus",
        "employment",
        "Are you currently employed in a postdoctoral position?",
        "boolean",
        True,
        "Select Yes only if your present UZH appointment is a postdoctoral position. "
        "If it will start later, select No and enter the future start date below.",
    ),
    _field("employmentStartDate", "employment", "UZH employment start date", "date", True),
    _field("employmentEndDate", "employment", "Expected UZH employment end date", "date", True),
    _field("futureStartDate", "employment", "Future UZH start date", "date"),
    _field("researchArea", "employment", "Molecular-life-sciences research area", "text", True),
    _field("clinicalWorkPercent", "employment", "Percentage of clinical work", "number", True),
    _field("firstAuthorDeclaration", "employment", "At least one first/co-first-author paper", "boolean", True),
    _field(
        "degrees",
        "qualifications",
        "Degrees",
        "degree_list",
        True,
        "Add each degree and its exact date of conferral.",
        ("BSc", "MA", "MD", "PhD"),
    ),
    _field("firstAuthorPaperCount", "publications", "First/co-first-author papers", "integer", True),
    _field("lastAuthorPaperCount", "publications", "Last/senior-author papers", "integer", True),
    _field("totalPaperCount", "publications", "Total papers", "integer", True),
    _field("hIndex", "publications", "h-index", "integer", True),
    _field("applicantReportedCitationTotal", "publications", "Applicant-reported citations", "integer", True),
    _field("orcid", "publications", "ORCID", "orcid"),
    _field(
        "hasGoogleScholarProfile",
        "publications",
        "Do you have a public Google Scholar profile?",
        "boolean",
        True,
    ),
    _field("googleScholarProfileUrl", "publications", "Google Scholar profile URL", "scholar_url"),
    _field(
        "publications",
        "publications",
        "Publications by DOI",
        "publication_list",
        help="Enter a DOI, check the publication found by the system, then confirm it.",
    ),
    _field(
        "contributionStatement",
        "contribution",
        "What do you consider your most important contribution to scientific advance to date?",
        "textarea",
        True,
        "Maximum 1,000 characters, approximately 200 words.",
    ),
)
_BY_CODE = {field.code: field for field in FIELD_INVENTORY}
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+\Z")


class FieldValidationError(ValueError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("One or more applicant fields are invalid.")
        self.errors = errors


def field_metadata() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            key: value
            for key, value in asdict(field).items()
            if value not in (False, "", ())
        }
        for field in FIELD_INVENTORY
    )


def validate_section(
    section: str, values: dict[str, object], *, final: bool
) -> dict[str, object]:
    definitions = tuple(field for field in FIELD_INVENTORY if field.section == section)
    if not definitions:
        raise FieldValidationError({"section": "The review section is invalid."})
    allowed = {field.code: field for field in definitions}
    errors: dict[str, str] = {}
    normalized: dict[str, object] = {}
    for code, raw in values.items():
        field = allowed.get(code)
        if field is None:
            errors[code] = "This field does not belong to the section."
            continue
        try:
            normalized[code] = _normalize(field, raw, final=final)
        except ValueError as error:
            errors[code] = str(error)

    if final:
        for field in definitions:
            if field.required and normalized.get(field.code) in (None, "", []):
                errors[field.code] = "This field is required."
    if section == "identity":
        month = normalized.get("birthMonth")
        year = normalized.get("birthYear")
        if month is not None and not 1 <= int(month) <= 12:
            errors["birthMonth"] = "Birth month must be between 1 and 12."
        if year is not None and not 1900 <= int(year) <= date.today().year:
            errors["birthYear"] = "Birth year is outside the supported range."
    if section == "employment":
        percent = normalized.get("clinicalWorkPercent")
        if percent is not None and not 0 <= float(percent) <= 100:
            errors["clinicalWorkPercent"] = "Clinical work must be between 0 and 100 percent."
        start = normalized.get("employmentStartDate")
        end = normalized.get("employmentEndDate")
        if start and end and start > end:
            errors["employmentEndDate"] = "Employment end date must not precede the start date."
    if section == "publications":
        for code in (
            "firstAuthorPaperCount", "lastAuthorPaperCount", "totalPaperCount", "hIndex",
            "applicantReportedCitationTotal",
        ):
            value = normalized.get(code)
            if value is not None and int(value) < 0:
                errors[code] = "The value cannot be negative."
        has_profile = normalized.get("hasGoogleScholarProfile")
        if has_profile is True and not normalized.get("googleScholarProfileUrl"):
            errors["googleScholarProfileUrl"] = "Enter the public Google Scholar profile URL."
        if has_profile is False:
            normalized["googleScholarProfileUrl"] = None
    if errors:
        raise FieldValidationError(errors)
    return normalized


def derive_ages(
    birth_year: int,
    birth_month: int,
    phd_date: date,
    call_deadline: date,
) -> dict[str, float]:
    months = call_deadline.year * 12 + call_deadline.month - (birth_year * 12 + birth_month)
    academic_days = (call_deadline - phd_date).days
    if months < 0 or academic_days < 0:
        raise ValueError("age source dates must not follow the call deadline")
    return {
        "anagraphicAge": round(months / 12, 1),
        "academicAge": round(academic_days / 365.2425, 1),
    }


def upgrade_legacy_section(section: str, values: dict[str, Any]) -> dict[str, Any]:
    """Present preserved pre-v17 JSON through the current applicant schema."""
    upgraded = dict(values)
    if section == "identity":
        if upgraded.get("gender") == "Self-describe":
            upgraded["gender"] = None
        upgraded.pop("genderSelfDescription", None)
    elif section == "employment":
        current = upgraded.get("postdoctoralEmploymentStatus")
        if not isinstance(current, bool) and current is not None:
            normalized = str(current).strip().casefold()
            if normalized in {"true", "yes", "employed", "current", "currently employed"}:
                upgraded["postdoctoralEmploymentStatus"] = True
            elif normalized in {
                "false", "no", "not employed", "unemployed", "none",
                "future", "future appointment", "not yet", "pending",
            }:
                upgraded["postdoctoralEmploymentStatus"] = False
            else:
                upgraded["postdoctoralEmploymentStatus"] = None
    elif section == "qualifications":
        if "degrees" not in upgraded:
            category = str(upgraded.get("degreeCategory") or "").strip().upper()
            phd_date = upgraded.get("phdDate") or None
            degrees: list[dict[str, object]] = []
            if category == "BSC":
                degrees.append({"degreeType": "BSc", "conferralDate": None})
            elif category == "MA":
                degrees.append({"degreeType": "MA", "conferralDate": None})
            elif category == "MD":
                degrees.append({"degreeType": "MD", "conferralDate": None})
            elif category == "PHD":
                degrees.append({"degreeType": "PhD", "conferralDate": phd_date})
            elif category == "MD_PHD":
                degrees.extend(
                    (
                        {"degreeType": "MD", "conferralDate": None},
                        {"degreeType": "PhD", "conferralDate": phd_date},
                    )
                )
            upgraded["degrees"] = degrees
        upgraded.pop("degreeCategory", None)
        upgraded.pop("phdDate", None)
    elif section == "publications":
        if "hasGoogleScholarProfile" not in upgraded:
            profile_url = upgraded.get("googleScholarProfileUrl")
            if isinstance(profile_url, str) and profile_url.strip():
                upgraded["hasGoogleScholarProfile"] = True
            elif upgraded.get("noGoogleScholarProfile") is True:
                upgraded["hasGoogleScholarProfile"] = False
            else:
                upgraded["hasGoogleScholarProfile"] = None
        upgraded.setdefault("publications", [])
        upgraded.pop("noGoogleScholarProfile", None)
        upgraded.pop("googleScholarCitationTotal", None)
    return upgraded


def upgrade_legacy_applicant(values: dict[str, Any]) -> dict[str, Any]:
    upgraded = dict(values)
    for section in ("identity", "employment", "qualifications", "publications"):
        upgraded = upgrade_legacy_section(section, upgraded)
    return upgraded


def _normalize(field: FieldDefinition, raw: object, *, final: bool) -> object:
    if field.kind in {"text", "email", "orcid", "scholar_url", "choice", "textarea"}:
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise ValueError("The value must be text.")
        value = unicodedata.normalize("NFC", raw).strip()
        if not value:
            return None
        maximum = 320 if field.kind == "email" else 2_000
        if len(value) > maximum:
            raise ValueError(f"The value must not exceed {maximum:,} characters.")
        if field.kind == "email" and _EMAIL.fullmatch(value) is None:
            raise ValueError("Enter a valid email address.")
        if field.kind == "choice" and value not in field.options:
            raise ValueError("Select one of the available choices.")
        if field.kind == "orcid" and not _valid_orcid(value):
            raise ValueError("Enter a valid ORCID.")
        if field.kind == "scholar_url" and not _valid_scholar_url(value):
            raise ValueError("Enter a public Google Scholar profile URL.")
        if field.kind == "textarea":
            try:
                return validate_contribution(raw)
            except ContributionError as error:
                raise ValueError(str(error)) from None
        return value
    if field.kind in {"integer", "number"}:
        if raw is None or raw == "":
            return None
        try:
            value = int(raw) if field.kind == "integer" else float(raw)
        except (TypeError, ValueError):
            raise ValueError("Enter a number.") from None
        if field.kind == "integer" and isinstance(raw, float) and not raw.is_integer():
            raise ValueError("Enter a whole number.")
        return value
    if field.kind == "boolean":
        if raw is None or raw == "":
            return None
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.casefold() in {"true", "false"}:
            return raw.casefold() == "true"
        raise ValueError("Choose yes or no.")
    if field.kind == "date":
        if raw is None or raw == "":
            return None
        try:
            return date.fromisoformat(str(raw))
        except ValueError:
            raise ValueError("Enter a valid date.") from None
    if field.kind == "degree_list":
        return _normalize_degrees(raw, field.options, final=final)
    if field.kind == "publication_list":
        return _normalize_publications(raw)
    raise ValueError("The field type is unsupported.")


def _normalize_degrees(
    raw: object, options: tuple[str, ...], *, final: bool
) -> list[dict[str, object]]:
    if raw is None or raw == "":
        return []
    if not isinstance(raw, list) or len(raw) > 20:
        raise ValueError("Enter no more than 20 degrees.")
    result: list[dict[str, object]] = []
    for row in raw:
        if not isinstance(row, dict) or set(row) != {"degreeType", "conferralDate"}:
            raise ValueError("Each degree requires a type and date of conferral.")
        degree_type = row["degreeType"]
        if degree_type in (None, "") and not final:
            normalized_type = None
        elif degree_type not in options:
            raise ValueError("Select BSc, MA, MD, or PhD for every degree.")
        else:
            normalized_type = degree_type
        raw_date = row["conferralDate"]
        if raw_date in (None, "") and not final:
            conferral_date = None
        else:
            try:
                conferral_date = date.fromisoformat(str(raw_date))
            except ValueError:
                raise ValueError("Enter a valid date of conferral for every degree.") from None
        result.append({"degreeType": normalized_type, "conferralDate": conferral_date})
    return result


def _normalize_publications(raw: object) -> list[dict[str, object]]:
    if raw is None or raw == "":
        return []
    if not isinstance(raw, list) or len(raw) > 200:
        raise ValueError("Enter no more than 200 publications.")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in raw:
        if not isinstance(row, dict) or set(row) != {"doi", "confirmed"}:
            raise ValueError("Each publication must contain a confirmed DOI.")
        try:
            doi = normalize_doi(row["doi"])
        except InvalidDoi:
            raise ValueError("Enter a valid DOI for every publication.") from None
        if row["confirmed"] is not True:
            raise ValueError("Confirm every publication before adding it.")
        if doi in seen:
            raise ValueError("Each DOI may be listed only once.")
        seen.add(doi)
        result.append({"doi": doi, "confirmed": True})
    return result


def _valid_orcid(value: str) -> bool:
    compact = value.replace("-", "")
    if re.fullmatch(r"\d{15}[\dX]", compact) is None:
        return False
    total = 0
    for digit in compact[:15]:
        total = (total + int(digit)) * 2
    result = (12 - total % 11) % 11
    expected = "X" if result == 10 else str(result)
    return compact[-1] == expected


def _valid_scholar_url(value: str) -> bool:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").casefold()
    return (
        parsed.scheme == "https"
        and (hostname == "scholar.google.com" or hostname.endswith(".scholar.google.com"))
        and parsed.path == "/citations"
    )
