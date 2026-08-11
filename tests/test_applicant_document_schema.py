from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "015_applicant_document_slots.sql"
VALIDATOR = ROOT / "database" / "tests" / "015_validate_applicant_document_slots.sql"
LEGACY_SLOT_WRITERS = (
    ROOT / "database" / "tests" / "007_validate_document_store.sql",
    ROOT / "database" / "tests" / "008_validate_import_provenance.sql",
    ROOT / "database" / "tests" / "009_validate_document_permissions.sql",
    ROOT / "app" / "importer" / "run.py",
)


def test_document_slot_release_enforces_session_scope_open_mode_and_history() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    normalized = source.replace("''", "'")

    for marker in (
        "ApplicantUploadMode",
        "ApplicantVisible",
        "SlotLabel",
        "RequiredForCompletion",
        "CREATE TABLE dbo.ApplicantDocumentSubmission",
        "CREATE PROCEDURE dbo.ValidateApplicantUploadSlot",
        "@SessionTokenSha256 binary(32)",
        "@ExpectedRowVersion binary(8)",
        "('CLOSED', 'MISSING', 'REPLACEMENT')",
        "('PENDING', 'ACCEPTED', 'REJECTED')",
        "DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantDocumentSubmission TO EHFApplicationRuntime",
    ):
        assert marker in normalized
    upload_procedure = source.split("CREATE PROCEDURE dbo.ValidateApplicantUploadSlot", 1)[1].split("END;\n');", 1)[0]
    assert "@ApplicationId" not in upload_procedure


def test_document_slot_columns_compile_before_slot_label_is_referenced() -> None:
    """Break caught: SQL Server cannot reference a newly added column in the same dynamic batch."""
    source = MIGRATION.read_text(encoding="utf-8")

    assert source.index("');") < source.index(
        "UPDATE dbo.DocumentSlot SET SlotLabel"
    )


def test_every_legacy_document_slot_insert_supplies_the_required_label() -> None:
    """Break caught: portal migration made SlotLabel mandatory for import and validation writers."""
    legacy_columns = "DocumentSlotId, ApplicationId, SlotCode, CreatedByIdentity"
    labelled_columns = (
        "DocumentSlotId, ApplicationId, SlotCode, SlotLabel, CreatedByIdentity"
    )

    for path in LEGACY_SLOT_WRITERS:
        source = path.read_text(encoding="utf-8")
        assert legacy_columns not in source
        assert labelled_columns in source


def test_document_slot_validator_is_present() -> None:
    assert "ValidateApplicantUploadSlot" in VALIDATOR.read_text(encoding="utf-8")
