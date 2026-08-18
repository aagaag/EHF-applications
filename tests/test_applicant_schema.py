"""Applicant access, draft, and confirmation schema release contracts."""

from __future__ import annotations

from pathlib import Path
import re

from app.migrations import discover_migrations


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "database" / "migrations"
VALIDATORS = ROOT / "database" / "tests"
DATABASE_SCRIPT = ROOT / "scripts" / "test-database.ps1"


def _migration(name: str) -> str:
    return (MIGRATIONS / name).read_text(encoding="utf-8")


def test_applicant_schema_release_is_ordered_and_has_isolated_validators() -> None:
    migrations = discover_migrations(MIGRATIONS)

    assert [migration.path.name for migration in migrations[10:13]] == [
        "011_applicant_access.sql",
        "012_applicant_drafts.sql",
        "013_applicant_confirmations.sql",
    ]
    assert [path.name for path in sorted(VALIDATORS.glob("01[123]_*.sql"))] == [
        "011_validate_applicant_access.sql",
        "012_validate_applicant_drafts.sql",
        "013_validate_applicant_confirmations.sql",
    ]


def test_access_schema_stores_only_hashes_and_binds_sessions_to_one_application() -> None:
    source = _migration("011_applicant_access.sql")

    for table in (
        "ApplicantInvitation",
        "ApplicantPreAuthContext",
        "ApplicantVerificationChallenge",
        "ApplicantSession",
        "ApplicantRateLimitBucket",
    ):
        assert f"CREATE TABLE dbo.{table}" in source
    for required in (
        "InvitationTokenSha256 binary(32) NOT NULL",
        "VerificationCodeHmacSha256 binary(32) NOT NULL",
        "ChallengeNonce binary(32) NOT NULL",
        "SessionTokenSha256 binary(32) NOT NULL",
        "CsrfTokenSha256 binary(32) NOT NULL",
        "ApplicationId uniqueidentifier NOT NULL",
        "PreAuthContextSha256 binary(32) NOT NULL",
        "AbsoluteExpiresAtUtc datetime2(7) NOT NULL",
        "IdleExpiresAtUtc datetime2(7) NOT NULL",
        "AttemptCount tinyint NOT NULL",
        "MaxAttempts tinyint NOT NULL",
        "ConsumedAtUtc datetime2(7) NULL",
        "RevokedAtUtc datetime2(7) NULL",
        "RowVersion rowversion NOT NULL",
    ):
        assert required in source
    assert not re.search(
        r"\b(?:InvitationToken|VerificationCode|SessionToken|CsrfToken)\s+n?varchar",
        source,
        flags=re.IGNORECASE,
    )
    assert "UQ_ApplicantInvitation_TokenHash" in source
    assert "UQ_ApplicantSession_TokenHash" in source
    assert "CK_ApplicantVerificationChallenge_Attempts" in source
    assert "CK_ApplicantSession_Expiry" in source


def test_draft_schema_has_optimistic_versions_and_immutable_corrections() -> None:
    source = _migration("012_applicant_drafts.sql")
    confirmation_source = _migration("013_applicant_confirmations.sql")

    assert "CREATE TABLE dbo.ApplicantSectionDraft" in source
    assert "DraftJson nvarchar(max) NOT NULL" in source
    assert "RowVersion rowversion NOT NULL" in source
    assert "UQ_ApplicantSectionDraft_ApplicationSection" in source
    assert "CREATE TABLE dbo.ApplicantFieldCorrection" in source
    assert "PreviousValueJson nvarchar(max) NULL" in source
    assert "NewValueJson nvarchar(max) NOT NULL" in source
    assert "CREATE TRIGGER dbo.TR_ApplicantFieldCorrection_AppendOnly" in source
    assert re.search(
        r"TR_ApplicantFieldCorrection_AppendOnly.*?INSTEAD OF UPDATE, DELETE",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert "CREATE PROCEDURE dbo.SaveApplicantSectionDraft" in source
    assert "@ExpectedRowVersion binary(8)" in source
    assert "The applicant draft changed before this update." in source
    assert "ApplicantReopenScope" in source
    assert "ScopeType = ''SECTION''" in source
    assert "ScopeCode = @SectionCode" in source
    assert "ClosedAtUtc IS NULL" in source
    assert "UPDATE dbo.ApplicantReopenScope" in confirmation_source
    assert "SET ClosedAtUtc = SYSUTCDATETIME()" in confirmation_source


def test_confirmation_schema_is_append_only_and_reopen_supersedes_final_state() -> None:
    source = _migration("013_applicant_confirmations.sql")
    document_source = _migration("015_applicant_document_slots.sql")

    for table in (
        "ApplicantSectionConfirmation",
        "ApplicantFinalConfirmation",
        "ApplicantReopenScope",
    ):
        assert f"CREATE TABLE dbo.{table}" in source
    for required in (
        "CanonicalSectionSha256 binary(32) NOT NULL",
        "ManifestJson nvarchar(max) NOT NULL",
        "ManifestSha256 binary(32) NOT NULL",
        "SupersededAtUtc datetime2(7) NULL",
        "ScopeType varchar(20) NOT NULL",
        "ScopeCode varchar(80) NOT NULL",
        "Reason nvarchar(1000) NOT NULL",
    ):
        assert required in source
    for table in ("ApplicantSectionConfirmation", "ApplicantFinalConfirmation"):
        assert re.search(
            rf"CREATE TRIGGER dbo\.TR_{table}_AppendOnly.*?"
            rf"ON dbo\.{table}.*?INSTEAD OF UPDATE, DELETE",
            source,
            flags=re.IGNORECASE | re.DOTALL,
        )
    assert "UX_ApplicantFinalConfirmation_Active" in source
    assert "WHERE SupersededAtUtc IS NULL" in source
    assert "CREATE PROCEDURE dbo.ReopenApplicantScope" in source
    assert "EHF-Administrators" in source
    assert "EHF-Applications-Administrators" not in source
    assert "UPDATE dbo.ApplicantFinalConfirmation" in source
    assert "SET SupersededAtUtc = SYSUTCDATETIME()" in source
    assert "UPDATE slot_row" in document_source
    assert "ApplicantUploadMode = ''REPLACEMENT''" in document_source
    assert "INSERT dbo.AuditEvent" in source
    assert "dbo.DocumentSlot" not in source
    assert "dbo.ApplicantDocumentSubmission" not in source
    assert "ALTER PROCEDURE dbo.ValidateApplicantFinalDocuments" in document_source


def test_runtime_has_execute_only_access_to_applicant_schema_operations() -> None:
    combined = "\n".join(
        _migration(name)
        for name in (
            "011_applicant_access.sql",
            "012_applicant_drafts.sql",
            "013_applicant_confirmations.sql",
        )
    )

    for table in (
        "ApplicantInvitation",
        "ApplicantPreAuthContext",
        "ApplicantVerificationChallenge",
        "ApplicantSession",
        "ApplicantRateLimitBucket",
        "ApplicantSectionDraft",
        "ApplicantFieldCorrection",
        "ApplicantSectionConfirmation",
        "ApplicantFinalConfirmation",
        "ApplicantReopenScope",
    ):
        assert (
            f"DENY SELECT, INSERT, UPDATE, DELETE ON dbo.{table} "
            "TO EHFApplicationRuntime;"
        ) in combined
    for procedure in (
        "SaveApplicantSectionDraft",
        "ConfirmApplicantSection",
        "SubmitApplicantFinalConfirmation",
    ):
        assert f"GRANT EXECUTE ON dbo.{procedure} TO EHFApplicationRuntime;" in combined
    assert "GRANT EXECUTE ON dbo.ReopenApplicantScope TO EHFApplicationRuntime;" not in combined


def test_confirmation_procedures_are_session_scoped_and_finalization_is_atomic() -> None:
    """Break caught: the browser could name an application or finalize stale work."""
    source = "\n".join(
        _migration(name)
        for name in (
            "012_applicant_drafts.sql",
            "013_applicant_confirmations.sql",
            "015_applicant_document_slots.sql",
        )
    )
    assert "CREATE PROCEDURE dbo.ConfirmApplicantSection" in source
    assert "CREATE PROCEDURE dbo.SubmitApplicantFinalConfirmation" in source
    submit = source[source.index("CREATE PROCEDURE dbo.SubmitApplicantFinalConfirmation") :]
    parameters = submit.split("AS", 1)[0]
    assert "@SessionTokenSha256 binary(32)" in parameters
    assert "@ApplicationId" not in parameters
    save = source[source.index("CREATE PROCEDURE dbo.SaveApplicantSectionDraft") :]
    save_parameters = save.split("AS", 1)[0]
    assert "@SessionTokenSha256 binary(32)" in save_parameters
    assert "@ApplicationId" not in save_parameters
    assert "BEGIN TRANSACTION" in submit
    assert "ApplicantSectionDraft" in submit
    assert "ApplicantSectionConfirmation" in submit
    assert "RequiredForCompletion" in submit
    assert "ApplicantDocumentSubmission" in submit
    assert "ApplicationStatus = ''CONFIRMED''" in submit
    assert "INSERT dbo.AuditEvent" in submit


def test_isolated_database_harness_applies_and_validates_release_nineteen() -> None:
    script = DATABASE_SCRIPT.read_text(encoding="utf-8")
    contract = (VALIDATORS / "001_validate_database_contract.sql").read_text(
        encoding="utf-8"
    )

    for name in (
        "011_applicant_access.sql",
        "011_validate_applicant_access.sql",
        "012_applicant_drafts.sql",
        "012_validate_applicant_drafts.sql",
        "013_applicant_confirmations.sql",
        "013_validate_applicant_confirmations.sql",
        "014_applicant_projection.sql",
        "014_validate_applicant_projection.sql",
        "015_applicant_document_slots.sql",
        "015_validate_applicant_document_slots.sql",
        "016_entra_applicant_workflow.sql",
            "016_validate_entra_applicant_workflow.sql",
            "017_applicant_form_simplification.sql",
            "017_validate_applicant_form_simplification.sql",
            "018_applicant_admin_preview.sql",
            "018_validate_applicant_admin_preview.sql",
            "019_synthetic_applicant_workspace.sql",
            "019_validate_synthetic_applicant_workspace.sql",
        ):
            assert name in script
    assert "Applied 19 migration\\(s\\)\\." in script
    assert "COUNT_BIG(*) FROM dbo.SchemaMigration) <> 19" in contract
    assert "WHERE MigrationCount = 19 AND CurrentVersion = 19" in contract
