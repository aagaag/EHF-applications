SET NOCOUNT ON;
SET XACT_ABORT ON;

ALTER TABLE dbo.UserPreference ADD
    DefaultCallMode varchar(40) NOT NULL
        CONSTRAINT DF_UserPreference_DefaultCallMode DEFAULT 'resume-last-opened',
    LastFellowshipCallId uniqueidentifier NULL,
    CONSTRAINT CK_UserPreference_DefaultCallMode CHECK
        (DefaultCallMode IN ('resume-last-opened', 'latest-application-deadline')),
    CONSTRAINT FK_UserPreference_LastFellowshipCall FOREIGN KEY (LastFellowshipCallId)
        REFERENCES dbo.FellowshipCall (FellowshipCallId);

EXEC(N'
CREATE PROCEDURE dbo.GetCallNavigationPreference
    @IdentityKey nvarchar(255)
WITH EXECUTE AS ''EHFPreferenceProcedureExecutor''
AS
BEGIN
    SET NOCOUNT ON;
    SET @IdentityKey = NULLIF(LTRIM(RTRIM(@IdentityKey)), N'''');
    IF @IdentityKey IS NULL
        THROW 54600, ''An identity key is required.'', 1;

    SELECT DefaultCallMode, LastFellowshipCallId
    FROM dbo.UserPreference
    WHERE IdentityKey = @IdentityKey;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.SetCallNavigationPreference
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
                 DefaultCallMode, LastFellowshipCallId)
            VALUES
                (@UserPreferenceId, @IdentityKey, @Email, @DisplayName,
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
                   @BeforeMode AS beforeMode,
                   CONVERT(nvarchar(36), @BeforeCallId) AS beforeCallId,
                   @DefaultCallMode AS afterMode,
                   CONVERT(nvarchar(36), @LastFellowshipCallId) AS afterCallId
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES
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

GRANT EXECUTE ON dbo.GetCallNavigationPreference TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.SetCallNavigationPreference TO EHFApplicationRuntime;

PRINT 'PASS 044 call navigation preferences';
