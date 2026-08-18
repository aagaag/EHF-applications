from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


PATH = Path(__file__).resolve().parents[1] / "scripts" / "reconcile-applicant-emails.py"
SPEC = spec_from_file_location("reconcile_applicant_emails", PATH)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_candidate_requires_repeated_evidence_or_name_bound_cv() -> None:
    assert MODULE.candidate_is_high_confidence(
        "sevasti.gaspari@example.test", given_names="Sevasti", family_name="Gaspari",
        document_count=1, found_in_cv=True, total_unique_emails=3,
    )
    assert MODULE.candidate_is_high_confidence(
        "unrelated@example.test", given_names="Sevasti", family_name="Gaspari",
        document_count=2, found_in_cv=False, total_unique_emails=3,
    )
    assert not MODULE.candidate_is_high_confidence(
        "referee@example.test", given_names="Sevasti", family_name="Gaspari",
        document_count=1, found_in_cv=False, total_unique_emails=3,
    )
    assert MODULE.candidate_is_high_confidence(
        "opaque-address@example.test", given_names="Sevasti", family_name="Gaspari",
        document_count=1, found_in_cv=False, total_unique_emails=1,
    )


def test_repeated_evidence_scores_above_single_document_contacts() -> None:
    assert MODULE.candidate_score(
        "opaque@example.test", given_names="Sevasti", family_name="Gaspari",
        document_count=2, found_in_cv=False,
    ) - MODULE.candidate_score(
        "referee@example.test", given_names="Sevasti", family_name="Gaspari",
        document_count=1, found_in_cv=True,
    ) >= 60
