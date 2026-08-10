SET NOCOUNT ON;
SET XACT_ABORT OFF;

IF OBJECT_ID(N'dbo.RuntimeHealth', N'P') IS NULL
    THROW 51500, 'The runtime health procedure is missing.', 1;
IF OBJECT_ID(N'dbo.SetUserPreference', N'P') IS NULL
    THROW 51501, 'The preference procedure is missing.', 1;
IF OBJECT_ID(N'dbo.SetApplicationStatus', N'P') IS NULL
    THROW 51502, 'The application-status procedure is missing.', 1;
IF OBJECT_ID(N'dbo.GetUserPreference', N'P') IS NULL
    THROW 51517, 'The preference-read procedure is missing.', 1;
IF OBJECT_ID(N'dbo.ValidateApplicationInvitation', N'P') IS NULL
    THROW 51518, 'The invitation-validation procedure is missing.', 1;
IF OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P') IS NULL
    THROW 51519, 'The internal-metrics procedure is missing.', 1;
IF DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime') IS NULL
    THROW 51503, 'The EHF runtime role is missing.', 1;
IF DATABASE_PRINCIPAL_ID(N'ehf_app') IS NULL
    THROW 51504, 'The EHF runtime user is missing.', 1;

DECLARE @RuntimeRoleId int = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime');
DECLARE @RuntimeUserId int = DATABASE_PRINCIPAL_ID(N'ehf_app');
DECLARE @ApprovedProcedures TABLE (ProcedureName sysname NOT NULL PRIMARY KEY);
INSERT @ApprovedProcedures VALUES
    (N'RuntimeHealth'), (N'SetUserPreference'), (N'GetUserPreference'),
    (N'SetApplicationStatus'), (N'ValidateApplicationInvitation'),
    (N'GetInternalApplicationMetrics');
DECLARE @ProtectedTables TABLE (TableName sysname NOT NULL PRIMARY KEY);
INSERT @ProtectedTables VALUES
    (N'SchemaMigration'), (N'FellowshipCall'), (N'Applicant'), (N'ApplicantContact'),
    (N'Application'), (N'EmploymentAffiliation'), (N'Qualification'),
    (N'EligibilityDeclaration'), (N'Bibliometrics'), (N'ContributionStatement'),
    (N'FieldProvenance'), (N'ApplicationSectionVersion'), (N'AuditEvent'), (N'UserPreference'),
    (N'DocumentSlot'), (N'Document'), (N'StoredObject'), (N'DocumentVersion'),
    (N'Recommendation'), (N'ImportRun'), (N'ImportRow'), (N'SourceOccurrence'),
    (N'CallSourceOccurrence'), (N'ImportException'), (N'ClassificationDecision');
DECLARE @RequiredDmlDenies TABLE (TableName sysname NOT NULL, PermissionName sysname NOT NULL, PRIMARY KEY (TableName, PermissionName));
INSERT @RequiredDmlDenies
SELECT TableName, PermissionName
FROM @ProtectedTables
CROSS JOIN (VALUES (N'SELECT'), (N'INSERT'), (N'UPDATE'), (N'DELETE')) AS permission_name(PermissionName);
DECLARE @ProtectedViews TABLE (ViewName sysname NOT NULL PRIMARY KEY);
INSERT @ProtectedViews VALUES
    (N'vw_ApplicantVisibleDocumentVersion'), (N'vw_InternalDocumentVersion');
DECLARE @ExpectedPermissions TABLE
(
    ClassId tinyint NOT NULL,
    MajorId int NOT NULL,
    MinorId int NOT NULL,
    PermissionName sysname COLLATE DATABASE_DEFAULT NOT NULL,
    StateDesc nvarchar(60) COLLATE DATABASE_DEFAULT NOT NULL,
    PRIMARY KEY (ClassId, MajorId, MinorId, PermissionName)
);
INSERT @ExpectedPermissions (ClassId, MajorId, MinorId, PermissionName, StateDesc) VALUES
    (0, 0, 0, N'CONNECT', N'GRANT'),
    (0, 0, 0, N'VIEW DEFINITION', N'DENY'),
    (0, 0, 0, N'CREATE TABLE', N'DENY'),
    (0, 0, 0, N'CREATE PROCEDURE', N'DENY'),
    (0, 0, 0, N'CREATE VIEW', N'DENY'),
    (0, 0, 0, N'ALTER ANY SCHEMA', N'DENY'),
    (0, 0, 0, N'ALTER ANY USER', N'DENY'),
    (0, 0, 0, N'ALTER ANY ROLE', N'DENY'),
    (3, SCHEMA_ID(N'dbo'), 0, N'ALTER', N'DENY'),
    (4, DATABASE_PRINCIPAL_ID(N'EHFPreferenceProcedureExecutor'), 0, N'IMPERSONATE', N'DENY');
INSERT @ExpectedPermissions (ClassId, MajorId, MinorId, PermissionName, StateDesc)
SELECT 1, OBJECT_ID(N'dbo.' + approved.ProcedureName, N'P'), 0, N'EXECUTE', N'GRANT'
FROM @ApprovedProcedures AS approved;
INSERT @ExpectedPermissions (ClassId, MajorId, MinorId, PermissionName, StateDesc)
SELECT 1, OBJECT_ID(N'dbo.' + required_deny.TableName, N'U'), 0, required_deny.PermissionName, N'DENY'
FROM @RequiredDmlDenies AS required_deny;
INSERT @ExpectedPermissions (ClassId, MajorId, MinorId, PermissionName, StateDesc)
SELECT 1, OBJECT_ID(N'dbo.' + protected_view.ViewName, N'V'), 0, N'SELECT', N'DENY'
FROM @ProtectedViews AS protected_view;

IF EXISTS
(
    SELECT 1
    FROM @ExpectedPermissions AS expected_permission
    WHERE NOT EXISTS
    (
        SELECT 1
        FROM sys.database_permissions AS permission_row
        WHERE permission_row.grantee_principal_id = @RuntimeRoleId
          AND permission_row.class = expected_permission.ClassId
          AND permission_row.major_id = expected_permission.MajorId
          AND permission_row.minor_id = expected_permission.MinorId
          AND permission_row.permission_name COLLATE DATABASE_DEFAULT = expected_permission.PermissionName
          AND permission_row.state_desc COLLATE DATABASE_DEFAULT = expected_permission.StateDesc
    )
)
    THROW 51505, 'The runtime role has a missing or altered permission row.', 1;
IF EXISTS
(
    SELECT 1
    FROM sys.database_permissions AS permission_row
    WHERE permission_row.grantee_principal_id = @RuntimeRoleId
      AND NOT EXISTS
      (
          SELECT 1
          FROM @ExpectedPermissions AS expected_permission
          WHERE permission_row.class = expected_permission.ClassId
            AND permission_row.major_id = expected_permission.MajorId
            AND permission_row.minor_id = expected_permission.MinorId
            AND permission_row.permission_name COLLATE DATABASE_DEFAULT = expected_permission.PermissionName
            AND permission_row.state_desc COLLATE DATABASE_DEFAULT = expected_permission.StateDesc
      )
)
    THROW 51506, 'The runtime role has an unapproved permission row or state.', 1;
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
IF
(
    SELECT COUNT(*) FROM sys.database_role_members
    WHERE role_principal_id = @RuntimeRoleId
) <> 1
OR NOT EXISTS
(
    SELECT 1 FROM sys.database_role_members
    WHERE role_principal_id = @RuntimeRoleId AND member_principal_id = @RuntimeUserId
)
    THROW 51513, 'The runtime role must contain only ehf_app.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM sys.database_principals AS role_row
    WHERE role_row.principal_id = @RuntimeRoleId
      AND role_row.type_desc = N'DATABASE_ROLE'
      AND role_row.owning_principal_id = DATABASE_PRINCIPAL_ID(N'dbo')
)
    THROW 51516, 'The runtime role must be owned by dbo.', 1;
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
