"""Behavior contracts for shared applicant citation-plot points."""

from __future__ import annotations

import re

from app.citation_plots import applicant_surname, citation_plot_points
from app.internal_preview import PreviewApplicantMetric


def test_surname_labels_keep_only_the_identifying_last_name() -> None:
    """Break caught: plot call-outs could expose given names or retain suffixes."""
    assert applicant_surname("Ada Lovelace") == "Lovelace"
    assert applicant_surname("Curie, Marie Skłodowska") == "Curie"
    assert applicant_surname("Jean-Pierre de la Cruz") == "Cruz"
    assert applicant_surname("Katherine Johnson Jr.") == "Johnson"
    assert applicant_surname("Smith Jr., Ada") == "Smith"
    assert applicant_surname("Curie IV, Eve") == "Curie"
    assert applicant_surname("Cher") == "Cher"


def test_plot_points_use_only_the_openalex_cutoff_and_exclude_incomplete_axes() -> None:
    """Break caught: labels could rank a fallback incorrectly or include unplottable data."""
    records = (
        PreviewApplicantMetric(
            applicant="Total Preferred",
            age=30,
                verified_citations=10,
        ),
        PreviewApplicantMetric(
            applicant="Scholar Fallback",
            age=31,
                verified_citations=20,
        ),
        PreviewApplicantMetric(applicant="Missing Citations", age=32),
        PreviewApplicantMetric(applicant="Missing Age", verified_citations=30),
    )

    points = citation_plot_points(records, "age")

    assert [(point.applicant, point.citations) for point in points] == [
        ("Total Preferred", 10.0),
        ("Scholar Fallback", 20.0),
    ]


def test_plot_points_prefer_a_verified_profile_total_over_self_report() -> None:
    """Break caught: a verified, source-attributed total could be ignored by reports."""
    records = (
        PreviewApplicantMetric(
            applicant="Profile Preferred",
            age=30,
            google_scholar_citations=20,
            verified_citations=30,
            verified_citation_source="OpenAlex",
        ),
    )

    points = citation_plot_points(records, "age")

    assert [(point.applicant, point.citations) for point in points] == [
        ("Profile Preferred", 30.0),
    ]


def test_plot_colors_heatmap_the_dataset_h_index_range_across_age_plots() -> None:
    """Break caught: graph colors could encode name order instead of H-index."""
    records = (
        PreviewApplicantMetric(
            applicant="Highest", age=30, academic_age=3,
            verified_citations=100, h_index=24,
        ),
        PreviewApplicantMetric(
            applicant="Lowest", age=31, academic_age=4,
            verified_citations=101, h_index=4,
        ),
        PreviewApplicantMetric(
            applicant="Middle", age=32, academic_age=5,
            verified_citations=102, h_index=14,
        ),
        PreviewApplicantMetric(
            applicant="Unavailable", age=33, academic_age=6,
            verified_citations=103, h_index=None,
        ),
    )

    age_points = citation_plot_points(records, "age")
    academic_points = citation_plot_points(records, "academic_age")
    age_colors = {point.source_index: point.color for point in age_points}
    academic_colors = {point.source_index: point.color for point in academic_points}

    assert age_colors == {
        0: "#0B6BCB",
        1: "#EEF0F1",
        2: "#85ADD6",
        3: "#B42318",
    }
    assert all(re.fullmatch(r"#[0-9A-F]{6}", color) for color in age_colors.values())
    assert academic_colors == age_colors
    assert citation_plot_points(records, "age") == age_points


def test_only_the_15_highest_citation_totals_receive_callouts() -> None:
    """Break caught: call-outs could label the wrong applicants or exceed 15."""
    records = tuple(
        PreviewApplicantMetric(
            applicant=f"Given Surname{index:02d}",
            age=30 + index,
            verified_citations=index,
        )
        for index in range(18)
    )

    points = citation_plot_points(records, "age")
    labelled = {point.applicant for point in points if point.labelled}

    assert labelled == {f"Given Surname{index:02d}" for index in range(3, 18)}
    assert {point.surname for point in points if point.labelled} == {
        f"Surname{index:02d}" for index in range(3, 18)
    }


def test_callout_ranking_breaks_citation_ties_by_name_then_source_order() -> None:
    """Break caught: equal citation totals could produce unstable call-out identities."""
    records = (
        PreviewApplicantMetric(applicant="Given Zulu", age=30, verified_citations=100),
        PreviewApplicantMetric(applicant="Given Alpha", age=31, verified_citations=100),
        PreviewApplicantMetric(applicant="Given Alpha", age=32, verified_citations=100),
    )

    points = citation_plot_points(records, "age", label_limit=2)

    assert [point.source_index for point in points if point.labelled] == [1, 2]
