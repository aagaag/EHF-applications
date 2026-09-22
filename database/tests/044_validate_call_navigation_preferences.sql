SET NOCOUNT ON;
SET XACT_ABORT ON;

IF COL_LENGTH(N'dbo.UserPreference', N'DefaultCallMode') IS NULL
   OR COL_LENGTH(N'dbo.UserPreference', N'LastFellowshipCallId') IS NULL
    THROW 54610, 'Call navigation preference columns are missing.', 1;
IF OBJECT_ID(N'dbo.GetCallNavigationPreference', N'P') IS NULL
   OR OBJECT_ID(N'dbo.SetCallNavigationPreference', N'P') IS NULL
    THROW 54611, 'Call navigation preference procedures are missing.', 1;
IF OBJECTPROPERTY(OBJECT_ID(N'dbo.GetCallNavigationPreference', N'P'), 'ExecIsExecuteAsUser') <> 1
   OR OBJECTPROPERTY(OBJECT_ID(N'dbo.SetCallNavigationPreference', N'P'), 'ExecIsExecuteAsUser') <> 1
    THROW 54612, 'Call navigation procedures do not use the protected executor.', 1;
IF NOT EXISTS
(
    SELECT 1 FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND major_id = OBJECT_ID(N'dbo.GetCallNavigationPreference', N'P')
      AND permission_name = N'EXECUTE' AND state IN (N'G', N'W')
)
    THROW 54613, 'Runtime cannot read call navigation preferences.', 1;

DECLARE @CallId uniqueidentifier =
    (SELECT TOP (1) FellowshipCallId FROM dbo.FellowshipCall ORDER BY ApplicationDeadlineUtc DESC);
BEGIN TRANSACTION;
EXEC dbo.SetCallNavigationPreference
    @IdentityKey = N'validator-call-navigation',
    @Email = N'validator@example.invalid',
    @DisplayName = N'Validator',
    @DefaultCallMode = 'latest-application-deadline',
    @LastFellowshipCallId = @CallId,
    @ActorIdentity = N'validator-call-navigation';
IF NOT EXISTS
(
    SELECT 1 FROM dbo.UserPreference
    WHERE IdentityKey = N'validator-call-navigation'
      AND DefaultCallMode = 'latest-application-deadline'
      AND LastFellowshipCallId = @CallId
)
    THROW 54614, 'The call navigation preference was not stored.', 1;
EXEC dbo.GetCallNavigationPreference @IdentityKey = N'validator-call-navigation';
ROLLBACK TRANSACTION;

IF NOT EXISTS
(
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.UserPreference')
      AND name = N'CK_UserPreference_DefaultCallMode'
      AND definition LIKE N'%resume-last-opened%'
      AND definition LIKE N'%latest-application-deadline%'
)
    THROW 54615, 'The default call mode constraint is incomplete.', 1;

PRINT 'PASS 044 call navigation preferences';
