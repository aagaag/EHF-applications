SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CallId uniqueidentifier =
    (SELECT FellowshipCallId FROM dbo.FellowshipCall WHERE CallCode = N'EHF-2026');
IF @CallId IS NULL THROW 54920, 'The 2026 call is missing.', 1;
IF (SELECT COUNT(*) FROM dbo.FellowshipCallEvaluator WHERE FellowshipCallId = @CallId) <> 3
    THROW 54921, 'The 2026 evaluator roster is incomplete.', 1;

IF EXISTS (
    SELECT old.ApplicationId, old.TrusteeCode, old.GroupCode,
           old.ModifiedByIdentity, old.RecordedAtUtc
    FROM dbo.TrusteeShortlistSelection AS old
    JOIN dbo.Application AS application_row ON application_row.ApplicationId = old.ApplicationId
    WHERE application_row.FellowshipCallId = @CallId
    EXCEPT
    SELECT current_row.ApplicationId, reviewer.LegacyTrusteeCode,
           current_row.GroupCode, current_row.ModifiedByIdentity,
           current_row.RecordedAtUtc
    FROM dbo.CallEvaluationSelection AS current_row
    JOIN dbo.FellowshipCallEvaluator AS reviewer
      ON reviewer.FellowshipCallEvaluatorId = current_row.FellowshipCallEvaluatorId
    WHERE current_row.FellowshipCallId = @CallId
)
    THROW 54922, 'A legacy evaluation was not preserved.', 1;

IF EXISTS (
    SELECT current_row.ApplicationId, reviewer.LegacyTrusteeCode,
           current_row.GroupCode, current_row.ModifiedByIdentity,
           current_row.RecordedAtUtc
    FROM dbo.CallEvaluationSelection AS current_row
    JOIN dbo.FellowshipCallEvaluator AS reviewer
      ON reviewer.FellowshipCallEvaluatorId = current_row.FellowshipCallEvaluatorId
    WHERE current_row.FellowshipCallId = @CallId
    EXCEPT
    SELECT old.ApplicationId, old.TrusteeCode, old.GroupCode,
           old.ModifiedByIdentity, old.RecordedAtUtc
    FROM dbo.TrusteeShortlistSelection AS old
    JOIN dbo.Application AS application_row ON application_row.ApplicationId = old.ApplicationId
    WHERE application_row.FellowshipCallId = @CallId
)
    THROW 54923, 'A call-scoped evaluation differs from the legacy source.', 1;

IF NOT EXISTS (
    SELECT 1 FROM sys.triggers WHERE name = N'TrusteeShortlistSelection_CallEvaluationMirror'
)
    THROW 54924, 'The legacy evaluation mirror is missing.', 1;

IF NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = N'FK_CallEvaluationSelection_Application'
) OR NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = N'FK_CallEvaluationSelection_Evaluator'
)
    THROW 54925, 'A call ownership constraint is missing.', 1;
