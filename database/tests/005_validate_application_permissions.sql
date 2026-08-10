SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.RuntimeHealth', N'P') IS NULL
    THROW 51500, 'The runtime health procedure is missing.', 1;
IF DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime') IS NULL
    THROW 51501, 'The EHF runtime role is missing.', 1;
IF DATABASE_PRINCIPAL_ID(N'ehf_app') IS NULL
    THROW 51502, 'The EHF runtime user is missing.', 1;

IF NOT EXISTS
(
    SELECT 1
    FROM sys.database_role_members AS membership
    WHERE membership.role_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND membership.member_principal_id = DATABASE_PRINCIPAL_ID(N'ehf_app')
)
    THROW 51503, 'The EHF runtime user is not assigned to its dedicated role.', 1;

DECLARE @ProtectedTables TABLE (TableName sysname NOT NULL PRIMARY KEY);
INSERT @ProtectedTables (TableName)
VALUES
    (N'SchemaMigration'),
    (N'FellowshipCall'),
    (N'Applicant'),
    (N'ApplicantContact'),
    (N'Application'),
    (N'EmploymentAffiliation'),
    (N'Qualification'),
    (N'EligibilityDeclaration'),
    (N'Bibliometrics'),
    (N'ContributionStatement'),
    (N'FieldProvenance'),
    (N'ApplicationSectionVersion'),
    (N'AuditEvent'),
    (N'UserPreference');

BEGIN TRANSACTION;
BEGIN TRY
    EXECUTE AS USER = N'ehf_app';

    IF HAS_PERMS_BY_NAME(N'dbo.RuntimeHealth', N'OBJECT', N'EXECUTE') <> 1
        THROW 51505, 'The runtime health procedure is not executable.', 1;
    IF HAS_PERMS_BY_NAME(N'dbo.SetUserPreference', N'OBJECT', N'EXECUTE') <> 1
        THROW 51506, 'The preference procedure is not executable.', 1;
    IF HAS_PERMS_BY_NAME(N'dbo.SetApplicationStatus', N'OBJECT', N'EXECUTE') <> 1
        THROW 51507, 'The application-status procedure is not executable.', 1;
    IF HAS_PERMS_BY_NAME(DB_NAME(), N'DATABASE', N'VIEW DEFINITION') <> 0
        THROW 51508, 'The runtime role can read database definitions.', 1;
    IF HAS_PERMS_BY_NAME(N'dbo', N'SCHEMA', N'ALTER') <> 0
        THROW 51509, 'The runtime role can alter the dbo schema.', 1;
    IF COALESCE(HAS_PERMS_BY_NAME(NULL, NULL, N'ALTER ANY LOGIN'), 0) <> 0
        THROW 51525, 'The runtime user can manage server logins.', 1;
    IF COALESCE(HAS_PERMS_BY_NAME(NULL, NULL, N'ALTER ANY SERVER ROLE'), 0) <> 0
        THROW 51526, 'The runtime user can manage server roles.', 1;

    IF EXISTS
    (
        SELECT 1
        FROM @ProtectedTables AS protected_table
        CROSS APPLY
        (
            VALUES (N'SELECT'), (N'INSERT'), (N'UPDATE'), (N'DELETE')
        ) AS operation (PermissionName)
        WHERE HAS_PERMS_BY_NAME
        (
            N'dbo.' + protected_table.TableName,
            N'OBJECT',
            operation.PermissionName
        ) <> 0
    )
        THROW 51510, 'The runtime user has direct EHF table access.', 1;

    DECLARE @Health TABLE (IsReady bit NOT NULL);
    INSERT @Health EXEC dbo.RuntimeHealth;
    IF NOT EXISTS (SELECT 1 FROM @Health WHERE IsReady = 1)
        THROW 51511, 'The runtime health procedure returned the wrong result.', 1;

    DECLARE @PreferenceResult TABLE
    (
        UserPreferenceId uniqueidentifier NOT NULL,
        IdentityKey nvarchar(255) NOT NULL,
        Email nvarchar(320) NOT NULL,
        DisplayName nvarchar(320) NOT NULL,
        Skin varchar(24) NOT NULL,
        InvertColors bit NOT NULL,
        CompactDensity bit NOT NULL,
        ReduceMotion bit NOT NULL,
        UpdatedAtUtc datetime2(7) NOT NULL,
        RowVersion binary(8) NOT NULL
    );
    INSERT @PreferenceResult
    EXEC dbo.SetUserPreference
        @IdentityKey = N'permission-validator-runtime',
        @Email = N'validator@example.invalid',
        @DisplayName = N'Permission validator runtime',
        @Skin = 'blue',
        @InvertColors = 0,
        @CompactDensity = 1,
        @ReduceMotion = 0,
        @ActorIdentity = N'permission-validator-runtime';
    IF @@TRANCOUNT <> 1
        THROW 51523, 'SetUserPreference did not preserve the caller transaction.', 1;

    BEGIN TRY
        SELECT TOP (1) UserPreferenceId FROM dbo.UserPreference;
        THROW 51512, 'The runtime user read a protected table.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() = 51512 THROW;
        IF ERROR_NUMBER() <> 229 THROW;
    END CATCH;

    BEGIN TRY
        DELETE FROM dbo.UserPreference WHERE 1 = 0;
        THROW 51513, 'The runtime user deleted from a protected table.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() = 51513 THROW;
        IF ERROR_NUMBER() <> 229 THROW;
    END CATCH;

    BEGIN TRY
        UPDATE dbo.UserPreference SET Skin = Skin WHERE 1 = 0;
        THROW 51514, 'The runtime user updated a protected table.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() = 51514 THROW;
        IF ERROR_NUMBER() <> 229 THROW;
    END CATCH;

    BEGIN TRY
        INSERT dbo.UserPreference
            (IdentityKey, Email, DisplayName, Skin,
             InvertColors, CompactDensity, ReduceMotion)
        VALUES
            (N'permission-validator-direct', N'validator@example.invalid',
             N'Permission validator', 'default', 0, 0, 0);
        THROW 51515, 'The runtime user inserted into a protected table.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() = 51515 THROW;
        IF ERROR_NUMBER() <> 229 THROW;
    END CATCH;

    BEGIN TRY
        EXEC(N'SELECT TOP (1) name FROM master.sys.databases;');
        THROW 51516, 'The runtime user read another database.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() = 51516 THROW;
    END CATCH;

    BEGIN TRY
        EXEC(N'CREATE TABLE dbo.PermissionValidatorDenied (Id int NOT NULL);');
        THROW 51517, 'The runtime user altered the dbo schema.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() = 51517 THROW;
    END CATCH;

    IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.SetUserPreference', N'P')) IS NOT NULL
        THROW 51518, 'The runtime user can read module definitions.', 1;
    IF EXISTS
    (
        SELECT 1
        FROM sys.database_principals
        WHERE name = N'EHFPreferenceProcedureExecutor'
    )
        THROW 51519, 'The runtime user can read protected principal metadata.', 1;

    BEGIN TRY
        EXEC(N'ALTER SERVER ROLE [sysadmin] ADD MEMBER [ehf_permission_validator_denied];');
        THROW 51520, 'The runtime user altered a server role.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() = 51520 THROW;
    END CATCH;

    BEGIN TRY
        EXEC(N'CREATE LOGIN [ehf_permission_validator_denied] WITH PASSWORD = ''x'';');
        THROW 51521, 'The runtime user created a login.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() = 51521 THROW;
    END CATCH;

    BEGIN TRY
        EXECUTE AS USER = N'EHFPreferenceProcedureExecutor';
        THROW 51522, 'The runtime user impersonated the preference executor.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() = 51522 THROW;
    END CATCH;

    REVERT;
    IF NOT EXISTS
    (
        SELECT 1
        FROM dbo.UserPreference AS preference_row
        INNER JOIN dbo.AuditEvent AS audit_row
            ON audit_row.EntityId = preference_row.UserPreferenceId
        WHERE preference_row.IdentityKey = N'permission-validator-runtime'
          AND audit_row.EventType = 'USER_PREFERENCE_SET'
    )
        THROW 51524, 'SetUserPreference did not write its audit event atomically.', 1;
    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF USER_NAME() = N'ehf_app' REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 005 application permissions';
