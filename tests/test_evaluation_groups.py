from dataclasses import FrozenInstanceError

import pytest

from app.evaluation_groups import EvaluationApplicant, group_applicants


ROSTER = ("ricky", "magda", "me")


def applicant(identifier, name, number, grades):
    return EvaluationApplicant(identifier, name, number, grades)


def test_groups_complete_evaluations_in_requested_order_and_sorts_deterministically():
    people = [
        applicant("3", "zoe", "E-2", {"ricky": "B", "magda": "C", "me": "C"}),
        applicant("2", "Alice", "E-10", {"ricky": "A", "magda": "A", "me": "B"}),
        applicant("1", "alice", "E-2", {"ricky": "A", "magda": "A", "me": "A"}),
        applicant("4", "Bob", "E-1", {"ricky": "B", "magda": "B", "me": "C"}),
        applicant("5", "Cara", "E-4", {"ricky": "C", "magda": "C", "me": "C"}),
        applicant("6", "Dan", "E-3", {"ricky": "A", "magda": "B", "me": "C"}),
    ]

    result = group_applicants(people, ROSTER)

    assert list(result.buckets) == ["AAA", "AAB", "ABB", "BBB", "BBC", "BCC", "CCC"]
    assert [p.id for p in result.buckets["AAA"]] == ["1"]
    assert [p.id for p in result.buckets["AAB"]] == ["2"]
    assert [p.id for p in result.buckets["BBC"]] == ["4"]
    assert [p.id for p in result.buckets["BCC"]] == ["3"]
    assert [p.id for p in result.buckets["CCC"]] == ["5"]
    assert [p.id for p in result.strong_discrepancy] == ["6"]


def test_partial_reviews_are_awaiting_and_a_c_is_flagged_immediately():
    people = [
        applicant("1", "Pending", "E-1", {"ricky": "B"}),
        applicant("2", "Flagged", "E-2", {"ricky": "A", "magda": "C"}),
    ]

    result = group_applicants(people, ROSTER)

    assert [p.id for p in result.awaiting_reviews] == ["2", "1"]
    assert [p.id for p in result.strong_discrepancy] == ["2"]
    assert [p.id for p in result.buckets["BBB"]] == ["1"]


@pytest.mark.parametrize(
    ("grades", "bucket"),
    [
        ({"ricky": "A", "magda": "A"}, "AAA"),
        ({"ricky": "A", "magda": "B"}, "AAB"),
        ({"ricky": "B", "magda": "B"}, "BBB"),
        ({"ricky": "B", "magda": "C"}, "BBC"),
        ({"ricky": "C", "magda": "C"}, "CCC"),
        ({"ricky": "A"}, "AAA"),
        ({"ricky": "B"}, "BBB"),
        ({"ricky": "C"}, "CCC"),
    ],
)
def test_incomplete_votes_are_grouped_by_available_grades_and_still_reported_as_awaiting(grades, bucket):
    person = applicant("1", "Applicant", "E-1", grades)

    result = group_applicants([person], ROSTER)

    assert result.buckets[bucket] == (person,)
    assert result.awaiting_reviews == (person,)


def test_immutable_applicant_and_input_mapping_is_not_changed():
    grades = {"ricky": "A", "magda": "B", "me": "C"}
    person = applicant("1", "Name", "E-1", grades)
    grades["ricky"] = "C"

    with pytest.raises(FrozenInstanceError):
        person.name = "Changed"
    assert person.grades["ricky"] == "A"


@pytest.mark.parametrize(
    "grades, roster",
    [
        ({"ricky": "D", "magda": "A", "me": "A"}, ROSTER),
        ({"ricky": "A", "other": "A", "me": "A"}, ROSTER),
        ({"ricky": "A", "magda": "A", "me": "A"}, ("ricky", "magda")),
        ({"ricky": "A", "magda": "A", "me": "A"}, ("ricky", "magda", "ricky")),
    ],
)
def test_rejects_invalid_grades_reviewers_and_rosters(grades, roster):
    with pytest.raises(ValueError):
        group_applicants([applicant("1", "Name", "E-1", grades)], roster)
