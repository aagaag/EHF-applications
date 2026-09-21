SET NOCOUNT ON;
SET XACT_ABORT ON;

IF EXISTS
(
    SELECT 1
    FROM sys.database_permissions AS permission_row
    JOIN sys.database_principals AS principal_row
      ON principal_row.principal_id = permission_row.grantee_principal_id
    WHERE principal_row.name = N'EHFApplicationRuntime'
      AND permission_row.class = 1
      AND permission_row.major_id = OBJECT_ID(N'dbo.ActivateCitationMetricCutoffRun', N'P')
      AND permission_row.permission_name = N'EXECUTE'
      AND permission_row.state IN (N'G', N'W')
)
    THROW 53200, 'The runtime role can activate citation metric cutoffs.', 1;

PRINT 'PASS 032 cutoff activation permissions';
