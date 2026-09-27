from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_call_evaluation_migration_has_call_owned_storage_and_legacy_parity():
    sql = (ROOT / "database/migrations/049_call_evaluation_groups.sql").read_text(encoding="utf-8")
    for fragment in (
        "CREATE TABLE dbo.FellowshipCallEvaluator",
        "CREATE TABLE dbo.CallEvaluationSelection",
        "FOREIGN KEY (FellowshipCallId, ApplicationId)",
        "FOREIGN KEY (FellowshipCallId, FellowshipCallEvaluatorId)",
        "FROM dbo.TrusteeShortlistSelection",
        "CREATE OR ALTER TRIGGER dbo.TrusteeShortlistSelection_CallEvaluationMirror",
        "CREATE OR ALTER PROCEDURE dbo.GetCallEvaluationOverview",
        "DENY SELECT, INSERT, UPDATE, DELETE ON dbo.CallEvaluationSelection",
    ):
        assert fragment in sql


def test_evaluation_comments_migration_preserves_magda_blanks_as_c_with_audit_and_owner_checks():
    sql = (ROOT / "database/migrations/050_call_evaluation_comments.sql").read_text(encoding="utf-8")
    assert "EXEC(N'\nALTER TABLE dbo.CallEvaluationSelection ADD CommentText" in sql
    assert sql.index("ALTER TABLE dbo.CallEvaluationSelection ADD CommentText") < sql.index(
        "CREATE OR ALTER PROCEDURE dbo.GetCallEvaluationOverview"
    )
    for fragment in (
        "ADD CommentText nvarchar(2000) NULL",
        "CREATE OR ALTER PROCEDURE dbo.SetCallEvaluationComment",
        "@ActorEntraObjectId uniqueidentifier",
        "@CommentText nvarchar(2000)",
        "ActorEntraObjectId = @ActorEntraObjectId",
        "InternalSelectionStatus = ''OPEN''",
        "''CALL_EVALUATION_COMMENT_SET''",
        "TrusteeCode = 'magda'",
        "GroupCode = 'C'",
        "@Actor nvarchar(255) = N'admin:adriano-aguzzi'",
        "AND old.GroupCode IS NULL",
    ):
        assert fragment in sql


def test_evaluation_comment_validator_checks_procedure_permissions_and_c_backfill():
    sql = (ROOT / "database/tests/050_validate_call_evaluation_comments.sql").read_text(encoding="utf-8")
    for fragment in (
        "dbo.SetCallEvaluationComment",
        "CommentText",
        "LegacyTrusteeCode = 'magda'",
        "GroupCode = 'C'",
        "EventType = 'SHORTLIST_SELECTION_SET'",
        "state = 'D'",
    ):
        assert fragment in sql
