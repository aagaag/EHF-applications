from __future__ import annotations

import pytest

from app.importer.match import ApplicantMatchError, match_applicants_to_folders, require_exact_matches
from app.importer.register import RegisterApplicant


def applicant(name: str) -> RegisterApplicant:
    return RegisterApplicant(
        applicant_name=name,
        degree=None,
        age_observation=None,
        academic_age_observation=None,
        gender=None,
        first_author_papers=None,
        last_author_papers=None,
        total_papers=None,
        h_index=None,
        total_citations=None,
        orcid=None,
        google_scholar_citations=None,
        identity_certainty=None,
    )


def test_exact_matching_uses_normalized_name_variants_and_reviewed_aliases_only() -> None:
    """Break caught: folder spelling variants could trigger an unreviewed fuzzy identity guess."""
    rows = (applicant("Müller, Ava"), applicant("Synthetic Person"), applicant("Zoe Example"))
    result = match_applicants_to_folders(
        rows,
        ("Ava Mueller", "Person_Synthetic", "reviewed-folder-03"),
        reviewed_aliases={"Zoe Example": "reviewed-folder-03"},
    )

    assert result.exceptions == ()
    assert [(match.applicant_name, match.folder_name) for match in result.matches] == [
        ("Müller, Ava", "Ava Mueller"),
        ("Synthetic Person", "Person_Synthetic"),
        ("Zoe Example", "reviewed-folder-03"),
    ]
    assert require_exact_matches(result) == result.matches


def test_matching_reports_zero_ambiguous_and_cross_row_matches_without_selecting_a_folder() -> None:
    """Break caught: an ambiguous register-to-folder relationship could create an application anyway."""
    result = match_applicants_to_folders(
        (applicant("Missing Person"), applicant("Ava Müller"), applicant("Repeated Name"), applicant("Repeated Name")),
        ("Ava Mueller", "Mueller Ava", "Repeated Name"),
    )

    assert result.matches == ()
    assert [exception.code for exception in result.exceptions] == [
        "no-folder-match",
        "ambiguous-folder-match",
        "cross-row-folder-match",
        "unmatched-source-folder",
        "unmatched-source-folder",
    ]
    with pytest.raises(ApplicantMatchError, match="no-folder-match"):
        require_exact_matches(result)


def test_compound_family_folder_requires_a_reviewed_alias() -> None:
    result = match_applicants_to_folders(
        (applicant("Carine Roese Mores"), applicant("Shayan Shami Pour")),
        ("Roese Mores", "Shami Pour"),
        reviewed_aliases={
            "Carine Roese Mores": "Roese Mores",
            "Shayan Shami Pour": "Shami Pour",
        },
    )

    assert result.exceptions == ()
    assert [match.folder_name for match in result.matches] == ["Roese Mores", "Shami Pour"]


def test_shared_surname_fragment_never_becomes_an_automatic_identity_match() -> None:
    result = match_applicants_to_folders(
        (applicant("John Smith"),),
        ("Jane Smith",),
    )

    assert result.matches == ()
    assert [exception.code for exception in result.exceptions] == [
        "no-folder-match",
        "unmatched-source-folder",
    ]
