SET NOCOUNT ON;

IF OBJECT_ID(N'dbo.ShortlistTrustee', N'U') IS NULL
    THROW 54420, 'The shortlist trustee mapping table is missing.', 1;
IF OBJECT_ID(N'dbo.TrusteeShortlistSelection', N'U') IS NULL
    THROW 54421, 'The shortlist selection table is missing.', 1;
IF OBJECT_ID(N'dbo.GetInternalShortlistSelections', N'P') IS NULL
    THROW 54422, 'The shortlist read procedure is missing.', 1;
IF OBJECT_ID(N'dbo.SetInternalShortlistSelection', N'P') IS NULL
    THROW 54423, 'The shortlist write procedure is missing.', 1;

IF (SELECT COUNT(*) FROM dbo.ShortlistTrustee) <> 3
    THROW 54424, 'Exactly three shortlist trustees must be configured.', 1;
IF NOT EXISTS (SELECT 1 FROM dbo.ShortlistTrustee WHERE TrusteeCode = 'ricky' AND ActorEntraObjectId = '7747ffa7-5193-4cc8-9221-08a1dd24b026')
    THROW 54425, 'Ricky shortlist identity is invalid.', 1;
IF NOT EXISTS (SELECT 1 FROM dbo.ShortlistTrustee WHERE TrusteeCode = 'magda' AND ActorEntraObjectId = '09d14671-38e1-4763-8d67-512c9787d379')
    THROW 54426, 'Magda shortlist identity is invalid.', 1;
IF NOT EXISTS (SELECT 1 FROM dbo.ShortlistTrustee WHERE TrusteeCode = 'adriano' AND ActorEntraObjectId = 'd5c5fb6a-f9c3-456c-97b1-20b450647f8c')
    THROW 54427, 'Adriano shortlist identity is invalid.', 1;

IF NOT EXISTS
(
    SELECT 1 FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND major_id = OBJECT_ID(N'dbo.GetInternalShortlistSelections')
      AND permission_name = N'EXECUTE' AND state IN ('G', 'W')
)
    THROW 54428, 'Runtime shortlist read execution is missing.', 1;
IF NOT EXISTS
(
    SELECT 1 FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND major_id = OBJECT_ID(N'dbo.SetInternalShortlistSelection')
      AND permission_name = N'EXECUTE' AND state IN ('G', 'W')
)
    THROW 54429, 'Runtime shortlist write execution is missing.', 1;
IF 4 <>
(
    SELECT COUNT(DISTINCT permission_name) FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND major_id = OBJECT_ID(N'dbo.TrusteeShortlistSelection')
      AND permission_name IN (N'SELECT', N'INSERT', N'UPDATE', N'DELETE') AND state = 'D'
)
    THROW 54430, 'Runtime must not update shortlist rows directly.', 1;
IF dbo.IsAuditPayloadKeyProhibited(N'trusteeCode') <> 0 OR dbo.IsAuditPayloadKeyProhibited(N'selected') <> 0
    THROW 54431, 'Shortlist audit payload keys are not allowlisted.', 1;
