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
        "birthMonth", "birthYear", "gender", "institute",
        "principalInvestigator", "positionTitle", "postdoctoralEmploymentStatus",
        "employmentStartDate", "employmentEndDate", "futureStartDate", "researchArea",
        "clinicalWorkPercent", "firstAuthorDeclaration", "degrees",
        "firstAuthorPaperCount", "lastAuthorPaperCount", "totalPaperCount", "hIndex",
        "applicantReportedCitationTotal", "orcid", "googleScholarProfileUrl",
        "hasGoogleScholarProfile", "publications", "contributionStatement",
    }
    assert {item["code"] for item in field_metadata()} == set(codes)
    gender = next(field for field in FIELD_INVENTORY if field.code == "gender")
    assert gender.options == ("Female", "Male", "Non-binary", "Prefer not to say")
    postdoc = next(
        field for field in FIELD_INVENTORY
        if field.code == "postdoctoralEmploymentStatus"
    )
    assert postdoc.kind == "boolean"
    assert postdoc.label == "Are you currently employed in a postdoctoral position?"
    assert "present UZH appointment" in postdoc.help


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
        (
            "qualifications",
            {"degrees": [{"degreeType": "PhD", "conferralDate": "not-a-date"}]},
            "degrees",
        ),
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
                "hasGoogleScholarProfile": None,
                "publications": [],
            },
            final=True,
        )

    assert "hasGoogleScholarProfile" in raised.value.errors


def test_repeatable_degrees_accept_only_complete_supported_rows() -> None:
    normalized = validate_section(
        "qualifications",
        {
            "degrees": [
                {"degreeType": "BSc", "conferralDate": "2011-06-30"},
                {"degreeType": "MA", "conferralDate": "2013-09-15"},
                {"degreeType": "MD", "conferralDate": "2017-12-01"},
                {"degreeType": "PhD", "conferralDate": "2019-05-20"},
            ]
        },
        final=True,
    )

    assert normalized["degrees"] == [
        {"degreeType": "BSc", "conferralDate": date(2011, 6, 30)},
        {"degreeType": "MA", "conferralDate": date(2013, 9, 15)},
        {"degreeType": "MD", "conferralDate": date(2017, 12, 1)},
        {"degreeType": "PhD", "conferralDate": date(2019, 5, 20)},
    ]

    for invalid in (
        [],
        [{"degreeType": "MSc", "conferralDate": "2019-05-20"}],
        [{"degreeType": "PhD"}],
        [{"degreeType": "PhD", "conferralDate": "2019-05-20", "notes": "x"}],
    ):
        with pytest.raises(FieldValidationError) as raised:
            validate_section("qualifications", {"degrees": invalid}, final=True)
        assert "degrees" in raised.value.errors


def test_incomplete_degree_row_can_autosave_but_cannot_be_confirmed() -> None:
    values = {"degrees": [{"degreeType": "MD", "conferralDate": ""}]}

    assert validate_section("qualifications", values, final=False) == {
        "degrees": [{"degreeType": "MD", "conferralDate": None}]
    }
    with pytest.raises(FieldValidationError) as raised:
        validate_section("qualifications", values, final=True)
    assert "degrees" in raised.value.errors


def test_google_scholar_url_is_required_only_for_a_public_profile() -> None:
    no_profile = validate_section(
        "publications",
        {"hasGoogleScholarProfile": False, "googleScholarProfileUrl": ""},
        final=False,
    )
    assert no_profile == {
        "hasGoogleScholarProfile": False,
        "googleScholarProfileUrl": None,
    }

    with pytest.raises(FieldValidationError) as raised:
        validate_section(
            "publications",
            {"hasGoogleScholarProfile": True, "googleScholarProfileUrl": ""},
            final=False,
        )
    assert "googleScholarProfileUrl" in raised.value.errors


def test_publication_list_persists_only_normalized_confirmed_dois() -> None:
    normalized = validate_section(
        "publications",
        {
            "publications": [
                {"doi": " https://doi.org/10.1000/ABC.123 ", "confirmed": True},
            ]
        },
        final=False,
    )
    assert normalized["publications"] == [
        {"doi": "10.1000/abc.123", "confirmed": True}
    ]

    for invalid in (
        [{"doi": "not a doi", "confirmed": True}],
        [{"doi": "10.1000/example", "confirmed": False}],
        [
            {"doi": "10.1000/example", "confirmed": True},
            {"doi": "https://doi.org/10.1000/EXAMPLE", "confirmed": True},
        ],
    ):
        with pytest.raises(FieldValidationError) as raised:
            validate_section("publications", {"publications": invalid}, final=False)
        assert "publications" in raised.value.errors


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
