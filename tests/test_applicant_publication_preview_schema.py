from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "022_applicant_publication_preview.sql"
VALIDATOR = ROOT / "database" / "tests" / "022_validate_applicant_publication_preview.sql"


def test_release_twenty_two_adds_admin_scoped_publications_to_the_preview() -> None:
    assert MIGRATION.exists()
    source = MIGRATION.read_text(encoding="utf-8")

    for fragment in (
        "ALTER PROCEDURE dbo.GetApplicantPreview",
        "@ActorGroup <> N''EHF-Administrators''",
        "@EmitPublications bit = 0",
        "dbo.ApplicationPublication",
        "dbo.PublicationCitationObservation",
        "SourceCode = ''GOOGLE_SCHOLAR''",
        "observation.ObservedAtUtc DESC",
        "CitationCount",
        "CitationStatus",
        "AuthorsText",
        "Title",
        "JournalText",
        "VolumeText",
        "PagesText",
        "PublicationYear",
        "ORDER BY publication_row.PublicationYear DESC",
    ):
        assert fragment in source


def test_release_twenty_two_validator_checks_scope_order_and_runtime_execution() -> None:
    assert VALIDATOR.exists()
    source = VALIDATOR.read_text(encoding="utf-8")

    for fragment in (
        "EXEC dbo.GetApplicantPreview",
        "@EmitPublications=0",
        "EHF-Trustees",
        "@PublicationRows",
        "Synthetic Preview Publication",
        "CompletedAtUtc",
        "CitationCount=41",
        "EHFApplicationRuntime",
        "ROLLBACK TRANSACTION",
        "PASS 022 applicant publication preview",
    ):
        assert fragment in source
