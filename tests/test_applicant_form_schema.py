from __future__ import annotations

from pathlib import Path

from app.migrations import discover_migrations


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "017_applicant_form_simplification.sql"
VALIDATOR = ROOT / "database" / "tests" / "017_validate_applicant_form_simplification.sql"


def test_release_seventeen_migrates_repeatable_degrees_and_simplified_projection() -> None:
    migrations = discover_migrations(ROOT / "database" / "migrations")
    assert migrations[-1].path.name == MIGRATION.name
    source = MIGRATION.read_text(encoding="utf-8")

    for fragment in (
        "ADD ConferralDate date NULL",
        "CK_Qualification_DegreeType",
        "'BSC', 'MA', 'MD', 'PHD'",
        "$.applicant.degrees",
        "$.applicant.hasGoogleScholarProfile",
        "$.applicant.publications",
        "$.applicant.genderSelfDescription",
        "$.applicant.googleScholarCitationTotal",
        "$.applicant.noGoogleScholarProfile",
    ):
        assert fragment in source

    assert "Historical one-shot rewrite intentionally disabled" in source
    assert "Expand only records with no section or final confirmation history" in source
    assert "FROM dbo.ApplicantSectionConfirmation AS section_confirmation" in source
    assert "TR_ApplicantSectionDraft_V17Compatibility" in source
    assert "requires the current portal version" in source
    assert "ALTER PROCEDURE dbo.SaveApplicantSectionDraft" in source
    assert "Merge a v16 qualifications write" in source
    assert "Preserve the list and derive the flag" in source
    assert "COUNT_BIG(*) > 1" in source
    assert "THROW 52027" in source
    assert "ALTER PROCEDURE dbo.GetApplicantSectionDraft\n" not in source
    assert "CREATE PROCEDURE dbo.GetApplicantSectionDraftV17" in source
    assert "ALTER PROCEDURE dbo.GetApplicantSectionConfirmation" in source
    assert "ALTER PROCEDURE dbo.ConfirmApplicantSection" in source
    assert "TR_ApplicantFinalConfirmation_ReopenValidation" in source
    assert "UQ_ApplicantSectionConfirmation_Version UNIQUE" in source
    assert "THROW 52144" in source
    assert "confirmation_row.ConfirmedAtUtc > open_scope.ReopenedAtUtc" in source
    assert "draft_row.SavedAtUtc > open_scope.ReopenedAtUtc" in source
    assert "UPDATE open_scope" in source
    assert "SET ClosedAtUtc = SYSUTCDATETIME()" in source


def test_release_seventeen_exposes_a_confirmation_bound_admin_correction_path() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    procedure = source.split(
        "CREATE PROCEDURE dbo.ReturnApplicantSubmissionForCorrection", 1
    )[1].split("GRANT EXECUTE ON dbo.ReturnApplicantSubmissionForCorrection", 1)[0]

    assert "@ApplicantFinalConfirmationId uniqueidentifier" in procedure
    assert "@ApplicationId uniqueidentifier" not in procedure
    assert "@ReviewerGroup <> ''EHF-Administrators''" in procedure
    assert "INSERT dbo.ApplicantReopenScope" in procedure


def test_release_seventeen_promotes_all_degrees_and_keeps_approval_provenance() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    promotion = source.split("ALTER PROCEDURE dbo.PromoteApprovedApplicantDrafts", 1)[1].split(
        "ALTER PROCEDURE dbo.GetInternalApplicationMetrics", 1
    )[0]
    promotion = promotion.replace("''", "'")

    assert "JSON_QUERY(@Qualifications, '$.degrees')" in promotion
    assert "OPENJSON(@Degrees)" in promotion
    assert "INSERT dbo.Qualification" in promotion
    assert "ConferralDate" in promotion
    assert "ApplicationSectionVersion" in promotion
    assert "FieldProvenance" in promotion
    assert "SourceType, SourceIdentifier" in promotion
    assert "'APPLICANT'" in promotion
    assert "JSON_VALUE(@Publications, '$.googleScholarCitationTotal')" not in promotion
    assert "JSON_QUERY(@Publications, '$.publications')" in promotion
    assert "WHEN 'employed' THEN CAST(1 AS bit)" in promotion
    assert "WHEN 'current' THEN CAST(1 AS bit)" in promotion
    assert "WHEN 'future' THEN CAST(0 AS bit)" in promotion
    assert "THROW 52646" in promotion

    metrics = source.split("ALTER PROCEDURE dbo.GetInternalApplicationMetrics", 1)[1]
    metrics = metrics.replace("''", "'")
    assert "OPENJSON(qualification_section.SnapshotJson, '$.degrees')" in metrics
    assert "STRING_AGG" in metrics
    assert "degreeType') = 'PhD'" in metrics
    assert "DATEDIFF(" in metrics and "day," in metrics
    assert "call_row.ApplicationDeadlineUtc" in metrics
    assert "PhdConferralDate" in metrics
    assert "'$.phdDate'" in metrics
    assert "'MD_PHD'" in metrics


def test_release_seventeen_validator_exercises_new_promotion_and_legacy_safety() -> None:
    validator = VALIDATOR.read_text(encoding="utf-8")

    for fragment in (
        "ConferralDate",
        '"degreeType":"BSc"',
        '"degreeType":"PhD"',
        '"hasGoogleScholarProfile":false',
        '"publications":[{"doi":"10.1000/example","confirmed":true}]',
        "EXEC dbo.PromoteApprovedApplicantDrafts",
        "SourceType='APPLICANT'",
        "ROLLBACK TRANSACTION",
        "PASS 017 applicant form simplification",
    ):
        assert fragment in validator
