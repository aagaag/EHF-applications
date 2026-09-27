"""Pure grouping of three-reviewer applicant evaluations."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal


Grade = Literal["A", "B", "C"]
ReviewerGrade = Grade | None
BUCKET_ORDER = ("AAA", "AAB", "ABB", "BBB", "BBC", "BCC", "CCC")


@dataclass(frozen=True)
class EvaluationApplicant:
    """An applicant and the grades received from the reviewer roster."""

    id: str
    name: str
    number: str
    grades: Mapping[str, ReviewerGrade]
    comments: Mapping[str, str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.grades, Mapping):
            raise ValueError("grades must be a reviewer-to-grade mapping")
        invalid = set(self.grades.values()) - {"A", "B", "C", None}
        if invalid:
            raise ValueError("grades must be A, B, C, or None")
        comments = self.comments
        if not isinstance(comments, Mapping):
            raise ValueError("comments must be a reviewer-to-text mapping")
        if any(value is not None and (not isinstance(value, str) or len(value) > 2000) for value in comments.values()):
            raise ValueError("comments must be at most 2000 characters")
        object.__setattr__(self, "grades", MappingProxyType(dict(self.grades)))
        object.__setattr__(self, "comments", MappingProxyType(dict(comments)))


@dataclass(frozen=True)
class EvaluationGroups:
    """Ordered, read-only grouping results for a reviewer roster."""

    buckets: Mapping[str, tuple[EvaluationApplicant, ...]]
    strong_discrepancy: tuple[EvaluationApplicant, ...]
    awaiting_reviews: tuple[EvaluationApplicant, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "buckets", MappingProxyType(dict(self.buckets)))


def group_applicants(
    applicants: Sequence[EvaluationApplicant],
    reviewer_roster: Sequence[str],
) -> EvaluationGroups:
    """Group applicants by three reviewer grades without side effects."""

    roster = tuple(reviewer_roster)
    if len(roster) != 3 or len(set(roster)) != 3:
        raise ValueError("reviewer roster must contain exactly three unique keys")

    ordered_applicants = tuple(sorted(applicants, key=_sort_key))
    buckets: dict[str, list[EvaluationApplicant]] = {key: [] for key in BUCKET_ORDER}
    discrepancy: list[EvaluationApplicant] = []
    awaiting: list[EvaluationApplicant] = []

    for applicant in ordered_applicants:
        unknown_reviewers = set(applicant.grades) - set(roster)
        if unknown_reviewers:
            raise ValueError("applicant contains a reviewer outside the roster")

        grades = tuple(applicant.grades.get(reviewer) for reviewer in roster)
        completed = tuple(grade for grade in grades if grade is not None)
        has_discrepancy = "A" in completed and "C" in completed
        if has_discrepancy:
            discrepancy.append(applicant)
        if len(completed) < 3:
            awaiting.append(applicant)
        if not completed or has_discrepancy:
            continue

        # Map a partial ballot into the nearest existing group by extending
        # its strongest available grade; the rendered votes remain unchanged.
        signature = "".join(sorted(completed + (completed[0],) * (3 - len(completed))))
        if signature not in buckets:
            raise ValueError("unsupported grade combination")
        buckets[signature].append(applicant)

    return EvaluationGroups(
        buckets={key: tuple(value) for key, value in buckets.items()},
        strong_discrepancy=tuple(discrepancy),
        awaiting_reviews=tuple(awaiting),
    )


def _sort_key(applicant: EvaluationApplicant) -> tuple[str, str, str]:
    return (applicant.name.casefold(), applicant.number.casefold(), applicant.id.casefold())
