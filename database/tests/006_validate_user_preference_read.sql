SET NOCOUNT ON;
SET XACT_ABORT OFF;

IF OBJECT_ID(N'dbo.GetUserPreference', N'P') IS NULL
    THROW 51610, 'The preference-read procedure is missing.', 1;
IF OBJECTPROPERTY(OBJECT_ID(N'dbo.GetUserPreference', N'P'), 'ExecIsExecuteAsUser') <> 1
    THROW 51611, 'The preference-read procedure must execute as its restricted user.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND class = 1
      AND major_id = OBJECT_ID(N'dbo.GetUserPreference', N'P')
      AND minor_id = 0
      AND permission_name = N'EXECUTE'
      AND state_desc = N'GRANT'
)
    THROW 51612, 'The runtime role lacks the exact preference-read grant.', 1;

BEGIN TRY
    EXEC dbo.GetUserPreference @IdentityKey = N' ';
    THROW 51613, 'The preference-read procedure accepted a blank identity.', 1;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() <> 51600 THROW;
END CATCH;

EXEC dbo.GetUserPreference @IdentityKey = N'validator-missing-identity';

PRINT 'PASS 006 user preference read';
