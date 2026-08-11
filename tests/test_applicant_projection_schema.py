"""Applicant-scoped SQL projection release contracts."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "014_applicant_projection.sql"
VALIDATOR = ROOT / "database" / "tests" / "014_validate_applicant_projection.sql"


def test_projection_is_session_scoped_and_returns_only_safe_document_metadata() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE VIEW dbo.vw_ApplicantFacingApplication" in source
    procedure = re.search(
        r"CREATE PROCEDURE dbo\.GetApplicantFacingApplication(?P<body>.*?)END;\s*'\);",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert procedure is not None
    body = procedure.group("body")
    assert "@SessionTokenSha256 binary(32)" in body
    assert "@ApplicationId" not in body
    assert "FROM dbo.ApplicantSession" in body
    assert "session_row.RevokedAtUtc IS NULL" in body
    assert "session_row.IdleExpiresAtUtc > SYSUTCDATETIME()" in body
    assert "session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME()" in body
    assert "FROM dbo.vw_ApplicantVisibleDocumentVersion" in body
    for forbidden in ("ObjectKey", "StoredObjectId", "Recommendation", "InternalNote"):
        assert forbidden not in body


def test_runtime_can_execute_projection_but_cannot_read_its_views_directly() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    validator = VALIDATOR.read_text(encoding="utf-8")

    assert "GRANT EXECUTE ON dbo.GetApplicantFacingApplication TO EHFApplicationRuntime;" in source
    assert "DENY SELECT ON dbo.vw_ApplicantFacingApplication TO EHFApplicationRuntime;" in source
    assert "GetApplicantFacingApplication" in validator
    assert "vw_ApplicantFacingApplication" in validator
