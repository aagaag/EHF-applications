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


def test_plot_points_preserve_citation_fallback_and_exclude_incomplete_axes() -> None:
    """Break caught: labels could rank a fallback incorrectly or include unplottable data."""
    records = (
        PreviewApplicantMetric(
            applicant="Total Preferred",
            age=30,
            total_citations=10,
            google_scholar_citations=999,
        ),
        PreviewApplicantMetric(
            applicant="Scholar Fallback",
            age=31,
            google_scholar_citations=20,
        ),
        PreviewApplicantMetric(applicant="Missing Citations", age=32),
        PreviewApplicantMetric(applicant="Missing Age", total_citations=30),
    )

    points = citation_plot_points(records, "age")

    assert [(point.applicant, point.citations) for point in points] == [
        ("Total Preferred", 10.0),
        ("Scholar Fallback", 20.0),
    ]


def test_each_record_has_a_unique_color_shared_by_both_age_plots() -> None:
    """Break caught: one applicant could change or share color between plots."""
    records = tuple(
        PreviewApplicantMetric(
            applicant=f"Applicant Surname{index:02d}",
            age=30 + index,
            academic_age=3 + index,
            total_citations=100 + index,
        )
        for index in range(18)
    )

    age_points = citation_plot_points(records, "age")
    academic_points = citation_plot_points(records, "academic_age")
    age_colors = {point.source_index: point.color for point in age_points}
    academic_colors = {point.source_index: point.color for point in academic_points}

    assert len(set(age_colors.values())) == 18
    assert all(re.fullmatch(r"#[0-9A-F]{6}", color) for color in age_colors.values())
    assert academic_colors == age_colors
    assert citation_plot_points(records, "age") == age_points


def test_only_the_15_highest_citation_totals_receive_callouts() -> None:
    """Break caught: call-outs could label the wrong applicants or exceed 15."""
    records = tuple(
        PreviewApplicantMetric(
            applicant=f"Given Surname{index:02d}",
            age=30 + index,
            total_citations=index,
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
        PreviewApplicantMetric(applicant="Given Zulu", age=30, total_citations=100),
        PreviewApplicantMetric(applicant="Given Alpha", age=31, total_citations=100),
        PreviewApplicantMetric(applicant="Given Alpha", age=32, total_citations=100),
    )

    points = citation_plot_points(records, "age", label_limit=2)

    assert [point.source_index for point in points if point.labelled] == [1, 2]
