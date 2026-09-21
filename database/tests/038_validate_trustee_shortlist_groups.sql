SET NOCOUNT ON;

IF COL_LENGTH(N'dbo.TrusteeShortlistSelection', N'GroupCode') IS NULL
    THROW 54432, 'The shortlist group column is missing.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.TrusteeShortlistSelection')
      AND definition LIKE '%GroupCode%'
      AND definition LIKE '%''A''%'
      AND definition LIKE '%''B''%'
      AND definition LIKE '%''C''%'
)
    THROW 54433, 'The shortlist group constraint is missing.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.SetInternalShortlistSelection')) NOT LIKE '%@GroupCode char(1)%'
    THROW 54434, 'The shortlist write procedure does not accept a group.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalShortlistSelections')) NOT LIKE '%GroupCode%'
    THROW 54435, 'The shortlist read procedure does not return a group.', 1;
IF dbo.IsAuditPayloadKeyProhibited(N'group') <> 0
    THROW 54436, 'The shortlist group audit payload key is not allowlisted.', 1;
