SET NOCOUNT ON;
SET XACT_ABORT ON;

EXEC(N'
CREATE PROCEDURE dbo.GetUserPreference
    @IdentityKey nvarchar(255)
WITH EXECUTE AS ''EHFPreferenceProcedureExecutor''
AS
BEGIN
    SET NOCOUNT ON;

    SET @IdentityKey = NULLIF(LTRIM(RTRIM(@IdentityKey)), N'''');
    IF @IdentityKey IS NULL
        THROW 51600, ''An identity key is required.'', 1;

    SELECT
        UserPreferenceId,
        IdentityKey,
        Email,
        DisplayName,
        Skin,
        InvertColors,
        CompactDensity,
        ReduceMotion
    FROM dbo.UserPreference
    WHERE IdentityKey = @IdentityKey;
END;
');

GRANT EXECUTE ON dbo.GetUserPreference TO EHFApplicationRuntime;
