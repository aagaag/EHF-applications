SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @RuntimeRoleId int=DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime');
IF @RuntimeRoleId IS NULL
    THROW 54801, 'The runtime role is missing.', 1;
IF EXISTS
(
    SELECT 1 FROM sys.database_permissions
    WHERE grantee_principal_id=@RuntimeRoleId
      AND major_id=OBJECT_ID(N'dbo.RecordApplicationPublicationReview',N'P')
)
    THROW 54802, 'The runtime role retains a direct low-level publication-review permission.', 1;
IF NOT EXISTS
(
    SELECT 1 FROM sys.database_permissions
    WHERE grantee_principal_id=@RuntimeRoleId
      AND major_id=OBJECT_ID(N'dbo.RecordPendingPublicationReview',N'P')
      AND permission_name=N'EXECUTE' AND state_desc=N'GRANT'
)
    THROW 54803, 'The approved pending-publication review boundary is unavailable.', 1;

PRINT 'PASS 048 publication review permission';
