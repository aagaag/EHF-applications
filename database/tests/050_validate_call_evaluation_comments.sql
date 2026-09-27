SET NOCOUNT ON;
SET XACT_ABORT ON;

IF COL_LENGTH(N'dbo.CallEvaluationSelection', N'CommentText') IS NULL
   OR COL_LENGTH(N'dbo.CallEvaluationSelection', N'CommentModifiedByIdentity') IS NULL
   OR COL_LENGTH(N'dbo.CallEvaluationSelection', N'CommentRecordedAtUtc') IS NULL
    THROW 55020, 'Evaluation comment storage is incomplete.', 1;

IF OBJECT_ID(N'dbo.SetCallEvaluationComment', N'P') IS NULL
   OR OBJECT_ID(N'dbo.GetCallEvaluationOverview', N'P') IS NULL
    THROW 55021, 'The evaluation comment procedures are missing.', 1;

IF (SELECT COUNT(*) FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND permission_name = N'EXECUTE' AND state = 'G'
      AND major_id IN (OBJECT_ID(N'dbo.SetCallEvaluationComment'),
                       OBJECT_ID(N'dbo.GetCallEvaluationOverview'))) <> 2
    THROW 55022, 'Runtime procedure permissions are incomplete.', 1;

IF (SELECT COUNT(DISTINCT permission_name) FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND major_id = OBJECT_ID(N'dbo.CallEvaluationSelection')
      AND permission_name IN (N'SELECT', N'INSERT', N'UPDATE', N'DELETE')
      AND state = 'D') <> 4
    THROW 55023, 'Runtime direct access to evaluations must remain denied.', 1;

IF EXISTS (
    SELECT 1
    FROM dbo.CallEvaluationSelection
    WHERE (CommentText IS NULL AND (CommentModifiedByIdentity IS NOT NULL OR CommentRecordedAtUtc IS NOT NULL))
       OR (CommentText IS NOT NULL AND (CommentModifiedByIdentity IS NULL OR CommentRecordedAtUtc IS NULL))
       OR LEN(CommentText) > 2000
)
    THROW 55024, 'Evaluation comment audit metadata is inconsistent.', 1;

IF EXISTS (
    SELECT 1
    FROM dbo.Application AS application_row
    JOIN dbo.FellowshipCall AS call_row ON call_row.FellowshipCallId = application_row.FellowshipCallId
    JOIN dbo.FellowshipCallEvaluator AS reviewer
      ON reviewer.FellowshipCallId = call_row.FellowshipCallId
     AND reviewer.LegacyTrusteeCode = 'magda'
    LEFT JOIN dbo.CallEvaluationSelection AS selection_row
      ON selection_row.FellowshipCallId = call_row.FellowshipCallId
     AND selection_row.ApplicationId = application_row.ApplicationId
     AND selection_row.FellowshipCallEvaluatorId = reviewer.FellowshipCallEvaluatorId
    WHERE call_row.CallCode = N'EHF-2026'
      AND selection_row.GroupCode IS NULL
)
    THROW 55025, 'Magda still has an unassigned EHF-2026 evaluation.', 1;

IF EXISTS (
    SELECT 1
    FROM dbo.CallEvaluationSelection AS selection_row
    JOIN dbo.FellowshipCallEvaluator AS reviewer
      ON reviewer.FellowshipCallEvaluatorId = selection_row.FellowshipCallEvaluatorId
    JOIN dbo.FellowshipCall AS call_row ON call_row.FellowshipCallId = selection_row.FellowshipCallId
    WHERE call_row.CallCode = N'EHF-2026' AND reviewer.LegacyTrusteeCode = 'magda'
      AND selection_row.GroupCode = 'C'
      AND selection_row.ModifiedByIdentity = N'admin:adriano-aguzzi'
      AND NOT EXISTS (
          SELECT 1 FROM dbo.AuditEvent AS audit_row
          WHERE audit_row.ApplicationId = selection_row.ApplicationId
            AND audit_row.EventType = 'SHORTLIST_SELECTION_SET'
            AND audit_row.ActorIdentity = N'admin:adriano-aguzzi'
            AND audit_row.PayloadJson LIKE N'%"basis":"Magda confirmed blank scores were C%'
      )
)
    THROW 55026, 'A manually corrected Magda C score is missing its provenance audit.', 1;

PRINT 'PASS 050 call evaluation comments';
