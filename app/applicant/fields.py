"""Canonical server-owned applicant field inventory and validation."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any
from urllib.parse import urlparse

from app.applicant.contribution import ContributionError, validate_contribution


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
        options=("Female", "Male", "Non-binary", "Self-describe", "Prefer not to say"),
    ),
    _field("genderSelfDescription", "identity", "Gender self-description", "text"),
    _field("institute", "employment", "Current UZH institute or department", "text", True),
    _field("principalInvestigator", "employment", "Current principal investigator", "text", True),
    _field("positionTitle", "employment", "Current position title", "text", True),
    _field("postdoctoralEmploymentStatus", "employment", "Postdoctoral employment status", "text", True),
    _field("employmentStartDate", "employment", "UZH employment start date", "date", True),
    _field("employmentEndDate", "employment", "Expected UZH employment end date", "date", True),
    _field("futureStartDate", "employment", "Future UZH start date", "date"),
    _field("researchArea", "employment", "Molecular-life-sciences research area", "text", True),
    _field("clinicalWorkPercent", "employment", "Percentage of clinical work", "number", True),
    _field("firstAuthorDeclaration", "employment", "At least one first/co-first-author paper", "boolean", True),
    _field("degreeCategory", "qualifications", "Highest documented degree", "choice", True, options=("MD", "PHD", "MD_PHD")),
    _field("phdDate", "qualifications", "Exact PhD completion or conferral date", "date"),
    _field("firstAuthorPaperCount", "publications", "First/co-first-author papers", "integer", True),
    _field("lastAuthorPaperCount", "publications", "Last/senior-author papers", "integer", True),
    _field("totalPaperCount", "publications", "Total papers", "integer", True),
    _field("hIndex", "publications", "h-index", "integer", True),
    _field("applicantReportedCitationTotal", "publications", "Applicant-reported citations", "integer", True),
    _field("orcid", "publications", "ORCID", "orcid"),
    _field("googleScholarProfileUrl", "publications", "Google Scholar profile URL", "scholar_url"),
    _field("noGoogleScholarProfile", "publications", "I do not have a public Google Scholar profile", "boolean"),
    _field("googleScholarCitationTotal", "publications", "Google Scholar citations today", "integer", True),
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
            normalized[code] = _normalize(field, raw)
        except ValueError as error:
            errors[code] = str(error)

    if final:
        for field in definitions:
            if field.required and normalized.get(field.code) in (None, ""):
                errors[field.code] = "This field is required."
    if section == "identity":
        month = normalized.get("birthMonth")
        year = normalized.get("birthYear")
        if month is not None and not 1 <= int(month) <= 12:
            errors["birthMonth"] = "Birth month must be between 1 and 12."
        if year is not None and not 1900 <= int(year) <= date.today().year:
            errors["birthYear"] = "Birth year is outside the supported range."
        if normalized.get("gender") == "Self-describe" and not normalized.get("genderSelfDescription"):
            errors["genderSelfDescription"] = "Please provide the self-description."
    if section == "employment":
        percent = normalized.get("clinicalWorkPercent")
        if percent is not None and not 0 <= float(percent) <= 100:
            errors["clinicalWorkPercent"] = "Clinical work must be between 0 and 100 percent."
        start = normalized.get("employmentStartDate")
        end = normalized.get("employmentEndDate")
        if start and end and start > end:
            errors["employmentEndDate"] = "Employment end date must not precede the start date."
    if section == "qualifications":
        if normalized.get("degreeCategory") in {"PHD", "MD_PHD"} and not normalized.get("phdDate"):
            errors["phdDate"] = "An exact PhD date is required for this degree."
    if section == "publications":
        for code in (
            "firstAuthorPaperCount", "lastAuthorPaperCount", "totalPaperCount", "hIndex",
            "applicantReportedCitationTotal", "googleScholarCitationTotal",
        ):
            value = normalized.get(code)
            if value is not None and int(value) < 0:
                errors[code] = "The value cannot be negative."
        if final and not normalized.get("googleScholarProfileUrl") and not normalized.get("noGoogleScholarProfile"):
            errors["googleScholarProfileUrl"] = "Provide a profile URL or confirm that no public profile exists."
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


def _normalize(field: FieldDefinition, raw: object) -> object:
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
    raise ValueError("The field type is unsupported.")


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
