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

DECLARE @RuntimeRoleId int = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime');
DECLARE @RuntimeUserId int = DATABASE_PRINCIPAL_ID(N'ehf_app');
DECLARE @ApprovedProcedures TABLE (ProcedureName sysname NOT NULL PRIMARY KEY);
INSERT @ApprovedProcedures VALUES (N'RuntimeHealth'), (N'SetUserPreference'), (N'SetApplicationStatus');
DECLARE @ProtectedTables TABLE (TableName sysname NOT NULL PRIMARY KEY);
INSERT @ProtectedTables VALUES
    (N'SchemaMigration'), (N'FellowshipCall'), (N'Applicant'), (N'ApplicantContact'),
    (N'Application'), (N'EmploymentAffiliation'), (N'Qualification'),
    (N'EligibilityDeclaration'), (N'Bibliometrics'), (N'ContributionStatement'),
    (N'FieldProvenance'), (N'ApplicationSectionVersion'), (N'AuditEvent'), (N'UserPreference');
DECLARE @RequiredDmlDenies TABLE (TableName sysname NOT NULL, PermissionName sysname NOT NULL, PRIMARY KEY (TableName, PermissionName));
INSERT @RequiredDmlDenies
SELECT TableName, PermissionName
FROM @ProtectedTables
CROSS JOIN (VALUES (N'SELECT'), (N'INSERT'), (N'UPDATE'), (N'DELETE')) AS permission_name(PermissionName);

IF NOT EXISTS
(
    SELECT 1 FROM sys.database_permissions AS permission_row
    WHERE permission_row.grantee_principal_id = @RuntimeRoleId
      AND permission_row.class = 0
      AND permission_row.major_id = 0
      AND permission_row.minor_id = 0
      AND permission_row.permission_name = N'CONNECT'
      AND permission_row.state_desc = N'GRANT'
)
    THROW 51505, 'A required runtime CONNECT grant is missing.', 1;

IF EXISTS
(
    SELECT 1 FROM @ApprovedProcedures AS approved
    WHERE NOT EXISTS
    (
        SELECT 1 FROM sys.database_permissions AS permission_row
        WHERE permission_row.grantee_principal_id = @RuntimeRoleId
          AND permission_row.class = 1
          AND permission_row.major_id = OBJECT_ID(N'dbo.' + approved.ProcedureName, N'P')
          AND permission_row.minor_id = 0
          AND permission_row.permission_name = N'EXECUTE'
          AND permission_row.state_desc = N'GRANT'
    )
)
    THROW 51506, 'A required runtime procedure grant is missing.', 1;
IF EXISTS
(
    SELECT 1 FROM sys.database_permissions AS permission_row
    WHERE permission_row.grantee_principal_id = @RuntimeRoleId
      AND permission_row.permission_name = N'EXECUTE'
      AND permission_row.state_desc = N'GRANT'
      AND NOT
      (
          permission_row.class = 1
          AND permission_row.major_id IN
              (OBJECT_ID(N'dbo.RuntimeHealth', N'P'), OBJECT_ID(N'dbo.SetUserPreference', N'P'), OBJECT_ID(N'dbo.SetApplicationStatus', N'P'))
          AND permission_row.minor_id = 0
      )
)
    THROW 51507, 'The runtime role has an unapproved procedure grant.', 1;
IF EXISTS
(
    SELECT 1 FROM @RequiredDmlDenies AS required_deny
    WHERE NOT EXISTS
    (
        SELECT 1 FROM sys.database_permissions AS permission_row
        WHERE permission_row.grantee_principal_id = @RuntimeRoleId
          AND permission_row.class = 1
          AND permission_row.major_id = OBJECT_ID(N'dbo.' + required_deny.TableName, N'U')
          AND permission_row.minor_id = 0
          AND permission_row.permission_name COLLATE DATABASE_DEFAULT = required_deny.PermissionName
          AND permission_row.state_desc = N'DENY'
    )
)
    THROW 51508, 'A required runtime table DML deny is missing.', 1;
IF EXISTS
(
    SELECT 1 FROM sys.database_permissions AS permission_row
    WHERE permission_row.grantee_principal_id = @RuntimeRoleId
      AND permission_row.permission_name IN (N'SELECT', N'INSERT', N'UPDATE', N'DELETE')
      AND NOT EXISTS
      (
          SELECT 1 FROM @RequiredDmlDenies AS required_deny
          WHERE permission_row.class = 1
            AND permission_row.major_id = OBJECT_ID(N'dbo.' + required_deny.TableName, N'U')
            AND permission_row.minor_id = 0
            AND permission_row.permission_name COLLATE DATABASE_DEFAULT = required_deny.PermissionName
            AND permission_row.state_desc = N'DENY'
      )
)
    THROW 51509, 'The runtime role has an unapproved table DML permission.', 1;
IF EXISTS
(
    SELECT 1 FROM sys.database_permissions AS permission_row
    WHERE permission_row.grantee_principal_id = @RuntimeRoleId
      AND permission_row.state_desc = N'GRANT'
      AND NOT
      (
          permission_row.class = 0 AND permission_row.major_id = 0
          AND permission_row.minor_id = 0 AND permission_row.permission_name = N'CONNECT'
      )
      AND NOT
      (
          permission_row.class = 1 AND permission_row.minor_id = 0
          AND permission_row.permission_name = N'EXECUTE'
          AND permission_row.major_id IN
              (OBJECT_ID(N'dbo.RuntimeHealth', N'P'), OBJECT_ID(N'dbo.SetUserPreference', N'P'), OBJECT_ID(N'dbo.SetApplicationStatus', N'P'))
      )
)
    THROW 51510, 'The runtime role has an unapproved grant.', 1;
IF EXISTS (SELECT 1 FROM sys.database_permissions WHERE grantee_principal_id = @RuntimeUserId)
    THROW 51511, 'The runtime user has a direct permission.', 1;
IF EXISTS
(
    SELECT 1
    FROM sys.database_role_members AS membership
    INNER JOIN sys.database_principals AS role_row
      ON role_row.principal_id = membership.role_principal_id
    WHERE membership.member_principal_id = @RuntimeUserId
      AND role_row.name <> N'EHFApplicationRuntime'
)
    THROW 51512, 'The runtime user has an unexpected role.', 1;
IF NOT EXISTS
(
    SELECT 1 FROM sys.database_role_members
    WHERE role_principal_id = @RuntimeRoleId AND member_principal_id = @RuntimeUserId
)
    THROW 51513, 'The EHF runtime user is not assigned to its dedicated role.', 1;
IF EXISTS
(
    SELECT 1 FROM sys.database_role_members
    WHERE member_principal_id = @RuntimeRoleId
)
    THROW 51514, 'The runtime role is nested in another role.', 1;
IF EXISTS (SELECT 1 FROM sys.schemas WHERE principal_id = @RuntimeRoleId)
   OR EXISTS (SELECT 1 FROM sys.objects WHERE principal_id = @RuntimeRoleId)
   OR EXISTS (SELECT 1 FROM sys.database_principals WHERE owning_principal_id = @RuntimeRoleId)
    THROW 51515, 'The runtime role owns a database object.', 1;

-- Real-login grants, denials, cross-database access, and procedure behavior
-- are exercised only by infra/test-sql-login.sh. EXECUTE AS USER is not a
-- substitute because it does not reproduce a SQL login token.
PRINT 'PASS 005 application permissions';
