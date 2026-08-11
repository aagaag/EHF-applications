from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "015_applicant_document_slots.sql"
VALIDATOR = ROOT / "database" / "tests" / "015_validate_applicant_document_slots.sql"


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


def test_document_slot_validator_is_present() -> None:
    assert "ValidateApplicantUploadSlot" in VALIDATOR.read_text(encoding="utf-8")
