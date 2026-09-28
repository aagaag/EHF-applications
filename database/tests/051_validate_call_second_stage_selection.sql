SET NOCOUNT ON;

IF OBJECT_ID(N'dbo.CallSecondStageSelection', N'U') IS NULL
    THROW 55110, 'The second-stage selection table is missing.', 1;
IF OBJECT_ID(N'dbo.GetCallSecondStageSelections', N'P') IS NULL
   OR OBJECT_ID(N'dbo.SetCallSecondStageSelection', N'P') IS NULL
    THROW 55111, 'The second-stage selection procedures are missing.', 1;
IF NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_CallSecondStageSelection_Application'
)
    THROW 55112, 'Second-stage selections are not call-bound to applications.', 1;
IF NOT EXISTS (
    SELECT 1 FROM sys.database_permissions
    WHERE major_id = OBJECT_ID(N'dbo.CallSecondStageSelection')
      AND grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND permission_name = N'SELECT' AND state = N'D'
) THROW 55113, 'The runtime can access the second-stage table directly.', 1;
IF NOT EXISTS (
    SELECT 1 FROM sys.database_permissions
    WHERE major_id = OBJECT_ID(N'dbo.SetCallSecondStageSelection')
      AND grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND permission_name = N'EXECUTE' AND state = N'G'
) THROW 55114, 'The runtime cannot use the bounded second-stage procedure.', 1;
PRINT 'PASS 051 call second-stage selection';
