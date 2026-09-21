SET NOCOUNT ON;
SET XACT_ABORT OFF;

IF OBJECT_ID(N'dbo.InternalReviewArtifactProvenance', N'U') IS NULL
    THROW 54130, 'The internal review artifact provenance table is missing.', 1;
IF OBJECT_ID(N'dbo.TR_InternalReviewArtifactProvenance_AppendOnly', N'TR') IS NULL
    THROW 54131, 'The internal review artifact append-only trigger is missing.', 1;
IF OBJECT_ID(N'dbo.ListInternalReviewArtifacts', N'P') IS NULL
   OR OBJECT_ID(N'dbo.GetInternalReviewArtifact', N'P') IS NULL
    THROW 54132, 'The internal review artifact procedures are missing.', 1;

IF EXISTS
(
    SELECT 1
    FROM sys.database_permissions AS permission_row
    WHERE permission_row.grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND permission_row.major_id = OBJECT_ID(N'dbo.InternalReviewArtifactProvenance')
      AND permission_row.permission_name IN (N'SELECT', N'INSERT', N'UPDATE', N'DELETE')
      AND permission_row.state_desc <> N'DENY'
)
    THROW 54133, 'The runtime can directly access artifact provenance.', 1;

BEGIN TRY
    EXECUTE AS USER = N'ehf_app';
    EXEC dbo.ListInternalReviewArtifacts
        @ApplicationId='00000000-0000-0000-0000-000000000000',
        @ActorIdentity=N'validator', @ActorGroup=N'EHF-Trustees';
    REVERT;
END TRY
BEGIN CATCH
    IF USER_NAME() = N'ehf_app' REVERT;
    THROW;
END CATCH;

PRINT 'PASS 033 internal review artifacts';
