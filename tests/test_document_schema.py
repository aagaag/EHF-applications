"""Document-schema release contract tests."""

from __future__ import annotations

from pathlib import Path
import re

from app.migrations import discover_migrations


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "database" / "migrations"
VALIDATORS = ROOT / "database" / "tests"


def test_document_release_migrations_and_validators_are_discoverable() -> None:
    """Break caught: the document boundary could ship without an ordered SQL release."""
    migrations = discover_migrations(MIGRATIONS)

    assert [migration.path.name for migration in migrations[-3:]] == [
        "007_document_store.sql",
        "008_import_provenance.sql",
        "009_document_permissions.sql",
    ]
    assert [path.name for path in sorted(VALIDATORS.glob("00[789]_*.sql"))] == [
        "007_validate_document_store.sql",
        "008_validate_import_provenance.sql",
        "009_validate_document_permissions.sql",
    ]


def test_recommendation_confidentiality_uses_immutable_link_and_document_type() -> None:
    """Break caught: a linked recommendation could be retyped or exposed by a type-only guard."""
    document_store = (MIGRATIONS / "007_document_store.sql").read_text(encoding="utf-8")
    permissions = (MIGRATIONS / "009_document_permissions.sql").read_text(encoding="utf-8")
    document_store_validator = (
        VALIDATORS / "007_validate_document_store.sql"
    ).read_text(encoding="utf-8")
    permissions_validator = (
        VALIDATORS / "009_validate_document_permissions.sql"
    ).read_text(encoding="utf-8")

    for table_name in ("Document", "Recommendation"):
        assert re.search(
            rf"CREATE TRIGGER dbo\.TR_{table_name}_AppendOnly.*?"
            rf"ON dbo\.{table_name}.*?INSTEAD OF UPDATE, DELETE",
            document_store,
            flags=re.IGNORECASE | re.DOTALL,
        ), f"{table_name} identity/type must be append-only"

    assert re.search(
        r"CREATE TRIGGER dbo\.TR_Recommendation_RequiresRecommendationDocumentType.*?"
        r"AFTER INSERT.*?document_row\.DocumentType <> ''RECOMMENDATION_LETTER''",
        document_store,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for protection in (permissions,):
        assert re.search(
            r"JOIN dbo\.Recommendation AS recommendation_row.*?"
            r"WHERE decision_row\.Classification = ''APPLICANT_VISIBLE''.*?"
            r"\(document_row\.DocumentType = ''RECOMMENDATION_LETTER''.*?"
            r"OR recommendation_row\.RecommendationId IS NOT NULL\)",
            protection,
            flags=re.IGNORECASE | re.DOTALL,
        )
        assert re.search(
            r"WHERE document_row\.DocumentType <> ''RECOMMENDATION_LETTER''.*?"
            r"AND NOT EXISTS\s*\(.*?FROM dbo\.Recommendation AS recommendation_row.*?"
            r"recommendation_row\.DocumentId = document_row\.DocumentId",
            protection,
            flags=re.IGNORECASE | re.DOTALL,
        )
    for marker in (
        "recommendation link requires recommendation document type",
        "recommendation link is immutable",
    ):
        assert marker in document_store_validator
    assert "linked recommendation is excluded from applicant projection" in permissions_validator


def test_source_occurrence_version_must_belong_to_its_application() -> None:
    """Break caught: provenance could attach one application's version to another application."""
    provenance = (MIGRATIONS / "008_import_provenance.sql").read_text(encoding="utf-8")
    validator = (
        VALIDATORS / "008_validate_import_provenance.sql"
    ).read_text(encoding="utf-8")

    assert re.search(
        r"CREATE TRIGGER dbo\.TR_SourceOccurrence_DocumentVersionApplicationMatches.*?"
        r"ON dbo\.SourceOccurrence.*?AFTER INSERT.*?"
        r"JOIN dbo\.DocumentVersion AS version_row.*?"
        r"JOIN dbo\.Document AS document_row.*?"
        r"JOIN dbo\.DocumentSlot AS slot_row.*?"
        r"occurrence_row\.ApplicationId <> slot_row\.ApplicationId",
        provenance,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert "linked version belongs to another application" in validator
    assert "non-document occurrence permits null version" in validator


def test_new_contact_review_columns_are_constrained_in_a_deferred_batch() -> None:
    """Break caught: SQL Server compiles a later constraint before the new columns exist."""
    permissions = (MIGRATIONS / "009_document_permissions.sql").read_text(encoding="utf-8")

    assert re.search(
        r"EXEC\(N'\s*ALTER TABLE dbo\.ApplicantContact\s+ADD CONSTRAINT "
        r"CK_ApplicantContact_ReviewStatus.*?CK_ApplicantContact_ReviewEvidence.*?'\);",
        permissions,
        flags=re.IGNORECASE | re.DOTALL,
    )
