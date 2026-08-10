"""Importer confidentiality regressions for legacy recommendation material."""

import json

from app.importer.register import RegisterApplicant
from app.importer.run import _legacy_register_snapshot, _record_legacy_recommendation


class CaptureConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, statement: str, *parameters: object) -> None:
        self.calls.append((statement, parameters))


def test_legacy_recommendation_gets_an_authoritative_confidential_link() -> None:
    connection = CaptureConnection()

    _record_legacy_recommendation(connection, "document-id", "RECOMMENDATION_LETTER")

    assert len(connection.calls) == 1
    statement, parameters = connection.calls[0]
    assert "dbo.Recommendation" in statement
    assert "UNKNOWN_LEGACY" in statement
    assert parameters == ("document-id",)


def test_applicant_document_never_gets_a_recommendation_link() -> None:
    connection = CaptureConnection()

    _record_legacy_recommendation(connection, "document-id", "CV")

    assert connection.calls == []


def test_every_non_name_register_observation_is_preserved_for_confirmation() -> None:
    applicant = RegisterApplicant(
        applicant_name="Example Applicant",
        degree="PhD",
        age_observation=31,
        academic_age_observation=4.5,
        gender=None,
        first_author_papers=2,
        last_author_papers=None,
        total_papers=7,
        h_index=5,
        total_citations=101,
        orcid="0000-0000-0000-000X",
        google_scholar_citations=110,
        identity_certainty="reviewed",
        total_citations_qualifier=">",
    )

    snapshot = json.loads(_legacy_register_snapshot(applicant))

    assert "applicant_name" not in snapshot
    assert snapshot["academic_age_observation"] == 4.5
    assert snapshot["h_index"] == 5
    assert snapshot["orcid"] == "0000-0000-0000-000X"
    assert snapshot["total_citations_qualifier"] == ">"
