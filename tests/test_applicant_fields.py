from __future__ import annotations

from datetime import date

import pytest

from app.applicant.fields import (
    FIELD_INVENTORY,
    FieldValidationError,
    derive_ages,
    field_metadata,
    validate_section,
)


def test_inventory_contains_every_approved_applicant_field_once() -> None:
    """Break caught: a required review field could disappear or be defined inconsistently."""
    codes = [field.code for field in FIELD_INVENTORY]

    assert len(codes) == len(set(codes))
    assert set(codes) == {
        "fullName", "preferredName", "registeredEmail", "alternativeEmail", "telephone",
        "birthMonth", "birthYear", "gender", "genderSelfDescription", "institute",
        "principalInvestigator", "positionTitle", "postdoctoralEmploymentStatus",
        "employmentStartDate", "employmentEndDate", "futureStartDate", "researchArea",
        "clinicalWorkPercent", "firstAuthorDeclaration", "degreeCategory", "phdDate",
        "firstAuthorPaperCount", "lastAuthorPaperCount", "totalPaperCount", "hIndex",
        "applicantReportedCitationTotal", "orcid", "googleScholarProfileUrl",
        "noGoogleScholarProfile", "googleScholarCitationTotal", "contributionStatement",
    }
    assert {item["code"] for item in field_metadata()} == set(codes)


def test_partial_autosave_normalizes_unicode_and_preserves_zero_as_a_value() -> None:
    """Break caught: autosave could erase zero or retain unstable Unicode/line endings."""
    values = validate_section(
        "publications",
        {
            "firstAuthorPaperCount": 0,
            "lastAuthorPaperCount": "0",
            "totalPaperCount": "",
            "orcid": " 0000-0002-1825-0097 ",
        },
        final=False,
    )

    assert values == {
        "firstAuthorPaperCount": 0,
        "lastAuthorPaperCount": 0,
        "totalPaperCount": None,
        "orcid": "0000-0002-1825-0097",
    }


@pytest.mark.parametrize(
    ("section", "values", "error_field"),
    [
        ("identity", {"registeredEmail": "not-an-email"}, "registeredEmail"),
        ("identity", {"birthMonth": 13}, "birthMonth"),
        ("employment", {"clinicalWorkPercent": 100.01}, "clinicalWorkPercent"),
        ("qualifications", {"degreeCategory": "PHD", "phdDate": ""}, "phdDate"),
        ("publications", {"firstAuthorPaperCount": -1}, "firstAuthorPaperCount"),
        ("publications", {"orcid": "0000-0000-0000-0000"}, "orcid"),
        (
            "publications",
            {"googleScholarProfileUrl": "https://example.test/not-scholar"},
            "googleScholarProfileUrl",
        ),
    ],
)
def test_invalid_field_values_fail_on_the_specific_field(
    section: str, values: dict[str, object], error_field: str
) -> None:
    """Break caught: malformed applicant values could enter a confirmed section."""
    with pytest.raises(FieldValidationError) as raised:
        validate_section(section, values, final=False)

    assert error_field in raised.value.errors


def test_final_confirmation_requires_all_fields_and_profile_or_no_profile_choice() -> None:
    """Break caught: navigation alone could make an incomplete section confirmable."""
    with pytest.raises(FieldValidationError) as raised:
        validate_section(
            "publications",
            {
                "firstAuthorPaperCount": 1,
                "lastAuthorPaperCount": 0,
                "totalPaperCount": 3,
                "hIndex": 2,
                "applicantReportedCitationTotal": 10,
                "orcid": "0000-0002-1825-0097",
                "googleScholarProfileUrl": "",
                "noGoogleScholarProfile": False,
                "googleScholarCitationTotal": 10,
            },
            final=True,
        )

    assert "googleScholarProfileUrl" in raised.value.errors


def test_gender_is_optional_and_never_derived_from_name() -> None:
    """Break caught: the system could infer a sensitive field from identity text."""
    normalized = validate_section(
        "identity",
        {"fullName": "Synthetic Name", "gender": "Prefer not to say"},
        final=False,
    )

    assert normalized["gender"] == "Prefer not to say"
    assert "genderSelfDescription" not in normalized


def test_ages_are_server_derived_at_the_call_deadline() -> None:
    """Break caught: browsers could submit or calculate inconsistent age metrics."""
    ages = derive_ages(1990, 12, date(2018, 6, 30), date(2026, 6, 30))

    assert ages == {"anagraphicAge": 35.5, "academicAge": 8.0}
