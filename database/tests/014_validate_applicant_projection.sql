SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.vw_ApplicantFacingApplication', N'V') IS NULL
    THROW 52311, 'The applicant-facing application view is missing.', 1;
IF OBJECT_ID(N'dbo.GetApplicantFacingApplication', N'P') IS NULL
    THROW 52312, 'The session-scoped applicant projection procedure is missing.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND class = 1
      AND major_id = OBJECT_ID(N'dbo.GetApplicantFacingApplication', N'P')
      AND permission_name = N'EXECUTE'
      AND state_desc = N'GRANT'
)
    THROW 52313, 'The runtime role cannot execute the applicant projection.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND class = 1
      AND major_id = OBJECT_ID(N'dbo.vw_ApplicantFacingApplication', N'V')
      AND permission_name = N'SELECT'
      AND state_desc = N'DENY'
)
    THROW 52314, 'The runtime role can read the applicant-facing view directly.', 1;

PRINT 'PASS 014 applicant projection';
