SET NOCOUNT ON;
SET XACT_ABORT ON;

EXEC(N'
ALTER PROCEDURE dbo.SetCallNavigationPreference
    @IdentityKey nvarchar(255),
    @Email nvarchar(320),
    @DisplayName nvarchar(320),
    @DefaultCallMode varchar(40),
    @LastFellowshipCallId uniqueidentifier = NULL,
    @ActorIdentity nvarchar(255)
WITH EXECUTE AS ''EHFPreferenceProcedureExecutor''
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @UserPreferenceId uniqueidentifier;
    DECLARE @BeforeMode varchar(40);
    DECLARE @BeforeCallId uniqueidentifier;
    DECLARE @PayloadJson nvarchar(max);

    SET @IdentityKey = NULLIF(LTRIM(RTRIM(@IdentityKey)), N'''');
    SET @Email = NULLIF(LTRIM(RTRIM(@Email)), N'''');
    SET @DisplayName = NULLIF(LTRIM(RTRIM(@DisplayName)), N'''');
    SET @ActorIdentity = NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''');
    IF @IdentityKey IS NULL OR @Email IS NULL OR @DisplayName IS NULL
        THROW 54601, ''Identity, email, and display name are required.'', 1;
    IF @ActorIdentity IS NULL
        THROW 54602, ''An actor identity is required.'', 1;
    IF @DefaultCallMode NOT IN (''resume-last-opened'', ''latest-application-deadline'')
        THROW 54603, ''The default call mode is invalid.'', 1;
    IF @LastFellowshipCallId IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM dbo.FellowshipCall WHERE FellowshipCallId = @LastFellowshipCallId)
        THROW 54604, ''The last fellowship call does not exist.'', 1;

    BEGIN TRY
        BEGIN TRANSACTION;
        SELECT @UserPreferenceId = UserPreferenceId,
               @BeforeMode = DefaultCallMode,
               @BeforeCallId = LastFellowshipCallId
        FROM dbo.UserPreference WITH (UPDLOCK, HOLDLOCK)
        WHERE IdentityKey = @IdentityKey;

        IF @UserPreferenceId IS NULL
        BEGIN
            SET @UserPreferenceId = NEWID();
            INSERT dbo.UserPreference
                (UserPreferenceId, IdentityKey, Email, DisplayName,
                 Skin, InvertColors, CompactDensity, ReduceMotion,
                 DefaultCallMode, LastFellowshipCallId)
            VALUES
                (@UserPreferenceId, @IdentityKey, @Email, @DisplayName,
                 ''default'', 0, 0, 0,
                 @DefaultCallMode, @LastFellowshipCallId);
        END
        ELSE
        BEGIN
            UPDATE dbo.UserPreference
            SET Email = @Email,
                DisplayName = @DisplayName,
                DefaultCallMode = @DefaultCallMode,
                LastFellowshipCallId = @LastFellowshipCallId,
                UpdatedAtUtc = SYSUTCDATETIME()
            WHERE UserPreferenceId = @UserPreferenceId;
        END;

        SELECT @PayloadJson =
        (
            SELECT CONVERT(nvarchar(36), @UserPreferenceId) AS userPreferenceId,
                   JSON_QUERY
                   (
                       (SELECT @BeforeMode AS status,
                               CONVERT(nvarchar(36), @BeforeCallId) AS callId
                        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES)
                   ) AS [before],
                   JSON_QUERY
                   (
                       (SELECT @DefaultCallMode AS status,
                               CONVERT(nvarchar(36), @LastFellowshipCallId) AS callId
                        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES)
                   ) AS [after]
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        );
        INSERT dbo.AuditEvent
            (EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
        VALUES
            (''CALL_NAVIGATION_PREFERENCE_SET'', @ActorIdentity,
             ''UserPreference'', @UserPreferenceId, @PayloadJson);

        COMMIT TRANSACTION;
        SELECT DefaultCallMode, LastFellowshipCallId
        FROM dbo.UserPreference
        WHERE UserPreferenceId = @UserPreferenceId;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

PRINT 'PASS 046 call navigation audit payload';
