SET NOCOUNT ON;
SET XACT_ABORT OFF;

IF OBJECT_ID(N'dbo.RuntimeHealth', N'P') IS NULL
    THROW 51500, 'The runtime health procedure is missing.', 1;
IF OBJECT_ID(N'dbo.SetUserPreference', N'P') IS NULL
    THROW 51501, 'The preference procedure is missing.', 1;
IF OBJECT_ID(N'dbo.SetApplicationStatus', N'P') IS NULL
    THROW 51502, 'The application-status procedure is missing.', 1;
IF DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime') IS NULL
    THROW 51503, 'The EHF runtime role is missing.', 1;
IF DATABASE_PRINCIPAL_ID(N'ehf_app') IS NULL
    THROW 51504, 'The EHF runtime user is missing.', 1;
IF NOT EXISTS
(
    SELECT 1 FROM sys.database_role_members
    WHERE role_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND member_principal_id = DATABASE_PRINCIPAL_ID(N'ehf_app')
)
    THROW 51505, 'The EHF runtime user is not assigned to its dedicated role.', 1;

DECLARE @ApprovedProcedures TABLE (ProcedureName sysname NOT NULL PRIMARY KEY);
INSERT @ApprovedProcedures VALUES (N'RuntimeHealth'), (N'SetUserPreference'), (N'SetApplicationStatus');
IF EXISTS
(
    SELECT 1 FROM @ApprovedProcedures AS approved
    WHERE NOT EXISTS
    (
        SELECT 1 FROM sys.database_permissions AS permission_row
        WHERE permission_row.grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
          AND permission_row.permission_name = N'EXECUTE'
          AND permission_row.state_desc = N'GRANT'
          AND permission_row.major_id = OBJECT_ID(N'dbo.' + approved.ProcedureName, N'P')
    )
)
    THROW 51506, 'A required runtime procedure grant is missing.', 1;
IF EXISTS
(
    SELECT 1 FROM sys.database_permissions AS permission_row
    WHERE permission_row.grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND permission_row.permission_name = N'EXECUTE'
      AND permission_row.state_desc = N'GRANT'
      AND permission_row.major_id <> 0
      AND permission_row.major_id NOT IN
          (OBJECT_ID(N'dbo.RuntimeHealth', N'P'), OBJECT_ID(N'dbo.SetUserPreference', N'P'), OBJECT_ID(N'dbo.SetApplicationStatus', N'P'))
)
    THROW 51507, 'The runtime role has an unapproved procedure grant.', 1;
IF EXISTS
(
    SELECT 1 FROM sys.database_permissions AS permission_row
    WHERE permission_row.grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND permission_row.permission_name IN (N'SELECT', N'INSERT', N'UPDATE', N'DELETE')
      AND permission_row.state_desc <> N'DENY'
)
    THROW 51508, 'The runtime role has a non-denied table permission.', 1;

-- Real-login grants, denials, cross-database access, and procedure behavior
-- are exercised only by infra/test-sql-login.sh. EXECUTE AS USER is not a
-- substitute because it does not reproduce a SQL login token.
PRINT 'PASS 005 application permissions';
