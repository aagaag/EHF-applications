"""Contracts for source-attributed applicant citation-profile observations."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "024_applicant_citation_profiles.sql"
VALIDATOR = ROOT / "database" / "tests" / "024_validate_applicant_citation_profiles.sql"


def test_profile_observations_are_append_only_and_feed_the_internal_metrics_projection() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    for fragment in (
        "CREATE TABLE dbo.ApplicantCitationProfileObservation",
        "ApplicantCitationProfileObservationId uniqueidentifier",
        "ImportRunId uniqueidentifier NOT NULL",
        "SourceCode IN ('OPENALEX', 'SEMANTIC_SCHOLAR')",
        "ProfileUrl nvarchar(1000) NOT NULL",
        "CitationCount bigint NOT NULL",
        "ALTER PROCEDURE dbo.GetInternalApplicationMetrics",
        "profile_observation.CitationCount AS VerifiedCitationCount",
        "profile_observation.SourceCode AS VerifiedCitationSource",
        "profile_observation.ProfileUrl AS VerifiedCitationProfileUrl",
    ):
        assert fragment in source

    validator = VALIDATOR.read_text(encoding="utf-8")
    assert "ApplicantCitationProfileObservation" in validator
    assert "Verified citation profile observation" in validator
