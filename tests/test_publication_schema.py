"""Application publication schema release contracts."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "021_application_publications.sql"
VALIDATOR = (
    ROOT
    / "database"
    / "tests"
    / "021_validate_application_publications.sql"
)


def test_publication_release_creates_application_owned_canonical_and_evidence_tables() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    for table in (
        "ApplicationPublication",
        "ApplicationPublicationSourceOccurrence",
        "PublicationMetadataObservation",
        "PublicationCitationObservation",
    ):
        assert f"CREATE TABLE dbo.{table}" in source
        assert (
            f"DENY SELECT, INSERT, UPDATE, DELETE ON dbo.{table} "
            "TO EHFApplicationRuntime;"
        ) in source

    assert "FK_ApplicationPublication_Application" in source
    assert "REFERENCES dbo.Application (ApplicationId)" in source
    assert "UQ_ApplicationPublication_Identity" in source
    assert "UX_ApplicationPublication_Doi" in source
    assert "WHERE Doi IS NOT NULL" in source
    for field in (
        "Doi varchar(255) NULL",
        "HttpLink nvarchar(2048) NULL",
        "AuthorsText nvarchar(max) NULL",
        "Title nvarchar(2000) NULL",
        "JournalText nvarchar(1000) NULL",
        "VolumeText nvarchar(255) NULL",
        "PagesText nvarchar(255) NULL",
        "PublicationYear smallint NULL",
    ):
        assert field in source


def test_publication_release_enforces_no_overwrite_and_append_only_evidence() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TRIGGER dbo.TR_ApplicationPublication_NoOverwrite" in source
    assert "INSTEAD OF UPDATE, DELETE" in source
    assert "A non-blank publication value cannot be overwritten or cleared." in source
    for table in (
        "ApplicationPublicationSourceOccurrence",
        "PublicationMetadataObservation",
        "PublicationCitationObservation",
    ):
        assert re.search(
            rf"CREATE TRIGGER dbo\.TR_{table}_AppendOnly.*?"
            rf"ON dbo\.{table}.*?INSTEAD OF UPDATE, DELETE",
            source,
            flags=re.IGNORECASE | re.DOTALL,
        )


def test_citation_observations_require_a_count_only_for_observed_status() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    for status in (
        "OBSERVED",
        "MANUAL_REQUIRED",
        "NOT_AVAILABLE_FROM_SOURCE",
        "NOT_FOUND",
        "NOT_APPLICABLE",
    ):
        assert status in source
    assert "CitationCount bigint NULL" in source
    assert "CitationCount >= 0" in source
    assert "CitationStatus = 'OBSERVED' AND CitationCount IS NOT NULL" in source
    assert "CitationStatus <> 'OBSERVED' AND CitationCount IS NULL" in source


def test_publication_validator_checks_schema_permissions_and_no_overwrite_behavior() -> None:
    source = VALIDATOR.read_text(encoding="utf-8")

    for name in (
        "PK_ApplicationPublication",
        "PK_ApplicationPublicationSourceOccurrence",
        "PK_PublicationMetadataObservation",
        "PK_PublicationCitationObservation",
        "FK_ApplicationPublication_Application",
        "FK_ApplicationPublication_ImportRun",
        "FK_ApplicationPublicationSourceOccurrence_Publication",
        "FK_ApplicationPublicationSourceOccurrence_Run",
        "FK_PublicationMetadataObservation_Publication",
        "FK_PublicationMetadataObservation_Run",
        "FK_PublicationCitationObservation_Publication",
        "FK_PublicationCitationObservation_Run",
        "UQ_ApplicationPublication_Identity",
        "UX_ApplicationPublication_Doi",
        "UQ_ApplicationPublicationSourceOccurrence_Payload",
        "UQ_PublicationMetadataObservation_Payload",
        "UQ_PublicationCitationObservation_Payload",
        "CK_ApplicationPublication_WorkKey",
        "CK_ApplicationPublication_Doi",
        "CK_ApplicationPublication_Link",
        "CK_ApplicationPublication_Year",
        "CK_ApplicationPublication_Status",
        "CK_ApplicationPublicationSourceOccurrence_Type",
        "CK_ApplicationPublicationSourceOccurrence_Page",
        "CK_ApplicationPublicationSourceOccurrence_Citation",
        "CK_PublicationMetadataObservation_Source",
        "CK_PublicationMetadataObservation_Json",
        "CK_PublicationCitationObservation_Source",
        "CK_PublicationCitationObservation_Status",
        "CK_PublicationCitationObservation_Count",
        "CK_PublicationCitationObservation_StatusCount",
        "CK_PublicationCitationObservation_Evidence",
    ):
        assert name in source
    assert "actual.is_disabled=0" in source
    assert "actual.is_not_trusted=0" in source
    assert "backing_index.is_disabled=0" in source
    assert "parent_column.name=expected.ParentColumn" in source
    assert "referenced_column.name=expected.ReferencedColumn" in source

    for table in (
        "ApplicationPublication",
        "ApplicationPublicationSourceOccurrence",
        "PublicationMetadataObservation",
        "PublicationCitationObservation",
    ):
        assert f"OBJECT_ID(N'dbo.{table}', N'U')" in source
    assert "TR_ApplicationPublication_NoOverwrite" in source
    for required in (
        "FK_ApplicationPublication_Application",
        "UQ_ApplicationPublication_Identity",
        "UX_ApplicationPublication_Doi",
        "CK_PublicationCitationObservation_StatusCount",
        "TR_ApplicationPublicationSourceOccurrence_AppendOnly",
        "TR_PublicationMetadataObservation_AppendOnly",
        "TR_PublicationCitationObservation_AppendOnly",
    ):
        assert required in source
    assert "DELETE dbo.ApplicationPublicationSourceOccurrence" in source
    assert "DELETE dbo.PublicationMetadataObservation" in source
    assert "DELETE dbo.PublicationCitationObservation" in source
    assert "EHFApplicationRuntime" in source
    assert "ROLLBACK TRANSACTION" in source
    assert "PASS 021 application publications" in source
