from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "023_open_citation_sources.sql"
VALIDATOR = ROOT / "database" / "tests" / "023_validate_open_citation_sources.sql"


def test_release_twenty_three_adds_open_citation_sources_and_latest_preview_values() -> None:
    assert MIGRATION.exists()
    source = MIGRATION.read_text(encoding="utf-8")

    for fragment in (
        "DROP CONSTRAINT CK_PublicationCitationObservation_Source",
        "OPENALEX",
        "SEMANTIC_SCHOLAR",
        "ALTER PROCEDURE dbo.GetApplicantPreview",
        "OpenAlexCitationCount",
        "OpenAlexCitationStatus",
        "SemanticScholarCitationCount",
        "SemanticScholarCitationStatus",
        "observation.ObservedAtUtc DESC",
        "SourceCode = ''GOOGLE_SCHOLAR''",
    ):
        assert fragment in source


def test_release_twenty_three_validator_checks_both_sources_and_runtime_preview() -> None:
    assert VALIDATOR.exists()
    source = VALIDATOR.read_text(encoding="utf-8")

    for fragment in (
        "OPENALEX",
        "SEMANTIC_SCHOLAR",
        "OpenAlexCitationCount",
        "SemanticScholarCitationCount",
        "EXEC dbo.GetApplicantPreview",
        "EHFApplicationRuntime",
        "ROLLBACK TRANSACTION",
        "PASS 023 open citation sources",
    ):
        assert fragment in source
