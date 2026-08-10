SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE TABLE dbo.AuditEvent
(
    AuditEventId uniqueidentifier NOT NULL
        CONSTRAINT DF_AuditEvent_Id DEFAULT NEWSEQUENTIALID(),
    FellowshipCallId uniqueidentifier NULL,
    ApplicationId uniqueidentifier NULL,
    EventType varchar(100) NOT NULL,
    ActorIdentity nvarchar(255) NOT NULL,
    EntityType varchar(80) NOT NULL,
    EntityId uniqueidentifier NOT NULL,
    PayloadJson nvarchar(max) NOT NULL,
    OccurredAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_AuditEvent_OccurredAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_AuditEvent PRIMARY KEY (AuditEventId),
    CONSTRAINT FK_AuditEvent_FellowshipCall FOREIGN KEY (FellowshipCallId)
        REFERENCES dbo.FellowshipCall (FellowshipCallId),
    CONSTRAINT FK_AuditEvent_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT CK_AuditEvent_EventType CHECK (LEN(EventType) > 0),
    CONSTRAINT CK_AuditEvent_Actor CHECK (LEN(ActorIdentity) > 0),
    CONSTRAINT CK_AuditEvent_EntityType CHECK (LEN(EntityType) > 0),
    CONSTRAINT CK_AuditEvent_PayloadJson CHECK
        (ISJSON(PayloadJson) = 1 AND DATALENGTH(PayloadJson) <= 16000)
);

CREATE INDEX IX_AuditEvent_ApplicationOccurred
ON dbo.AuditEvent (ApplicationId, OccurredAtUtc, AuditEventId)
WHERE ApplicationId IS NOT NULL;

CREATE TABLE dbo.UserPreference
(
    UserPreferenceId uniqueidentifier NOT NULL
        CONSTRAINT DF_UserPreference_Id DEFAULT NEWSEQUENTIALID(),
    IdentityKey nvarchar(255) NOT NULL,
    Email nvarchar(320) NOT NULL,
    DisplayName nvarchar(320) NOT NULL,
    Skin varchar(24) NOT NULL,
    InvertColors bit NOT NULL,
    CompactDensity bit NOT NULL,
    ReduceMotion bit NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_UserPreference_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    UpdatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_UserPreference_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_UserPreference PRIMARY KEY (UserPreferenceId),
    CONSTRAINT UQ_UserPreference_IdentityKey UNIQUE (IdentityKey),
    CONSTRAINT CK_UserPreference_IdentityKey CHECK (LEN(IdentityKey) > 0),
    CONSTRAINT CK_UserPreference_Email CHECK (LEN(Email) > 0),
    CONSTRAINT CK_UserPreference_DisplayName CHECK (LEN(DisplayName) > 0),
    CONSTRAINT CK_UserPreference_Skin CHECK
        (Skin IN ('default', 'high-contrast', 'soft-earth', 'blue')),
    CONSTRAINT CK_UserPreference_Dates CHECK (UpdatedAtUtc >= CreatedAtUtc)
);

EXEC(N'
CREATE FUNCTION dbo.IsAuditPayloadKeyProhibited
(
    @JsonKey nvarchar(4000)
)
RETURNS bit
WITH SCHEMABINDING
AS
BEGIN
    DECLARE @NormalizedKey nvarchar(4000) = LOWER(COALESCE(@JsonKey, N''''));

    SET @NormalizedKey = REPLACE(@NormalizedKey, N''_'', N'''');
    SET @NormalizedKey = REPLACE(@NormalizedKey, N''-'', N'''');
    SET @NormalizedKey = REPLACE(@NormalizedKey, N'' '', N'''');
    SET @NormalizedKey = REPLACE(@NormalizedKey, N''.'', N'''');
    SET @NormalizedKey = REPLACE(@NormalizedKey, N''/'', N'''');
    SET @NormalizedKey = REPLACE(@NormalizedKey, N''\'', N'''');
    SET @NormalizedKey = REPLACE(@NormalizedKey, N'':'', N'''');

    IF @NormalizedKey IN
    (
        N''before'', N''after'',
        N''applicationid'', N''applicantid'', N''callid'',
        N''documentid'', N''requestid'', N''userpreferenceid'',
        N''status'', N''skin'', N''invertcolors'',
        N''compactdensity'', N''reducemotion''
    )
        RETURN 0;

    RETURN 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_AuditEvent_AppendOnly
ON dbo.AuditEvent
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 51031, ''Audit events are append-only.'', 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_AuditEvent_RejectSensitivePayload
ON dbo.AuditEvent
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @Unsafe bit = 0;

    ;WITH PayloadNode AS
    (
        SELECT
            inserted_row.AuditEventId,
            json_value.[key] AS JsonKey,
            json_value.value AS JsonValue,
            json_value.type AS JsonType
        FROM inserted AS inserted_row
        CROSS APPLY OPENJSON(inserted_row.PayloadJson) AS json_value

        UNION ALL

        SELECT
            parent.AuditEventId,
            child.[key],
            child.value,
            child.type
        FROM PayloadNode AS parent
        CROSS APPLY OPENJSON
        (
            CASE WHEN parent.JsonType IN (4, 5) THEN parent.JsonValue END
        ) AS child
    )
    SELECT TOP (1) @Unsafe = 1
    FROM PayloadNode
    WHERE dbo.IsAuditPayloadKeyProhibited(JsonKey) = 1;

    IF @Unsafe = 1
        THROW 51032, ''Audit payload contains a prohibited field.'', 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_UserPreference_ProcedureOnly
ON dbo.UserPreference
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF USER_NAME() <> N''dbo''
        THROW 51033, ''User preferences may be changed only through the approved procedure.'', 1;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.SetApplicationStatus
    @ApplicationId uniqueidentifier,
    @NewStatus varchar(20),
    @ActorIdentity nvarchar(255),
    @ExpectedRowVersion binary(8)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @BeforeStatus varchar(20);
    DECLARE @ActualRowVersion binary(8);
    DECLARE @FellowshipCallId uniqueidentifier;
    DECLARE @AfterRowVersion binary(8);
    DECLARE @PayloadJson nvarchar(max);

    IF @NewStatus NOT IN
        (''DRAFT'', ''IMPORTED'', ''INVITED'', ''IN_REVIEW'', ''CONFIRMED'', ''WITHDRAWN'')
        THROW 51034, ''The requested application status is invalid.'', 1;
    IF NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
        THROW 51035, ''An actor identity is required.'', 1;

    BEGIN TRY
        BEGIN TRANSACTION;

        SELECT
            @BeforeStatus = ApplicationStatus,
            @ActualRowVersion = RowVersion,
            @FellowshipCallId = FellowshipCallId
        FROM dbo.Application WITH (UPDLOCK, HOLDLOCK)
        WHERE ApplicationId = @ApplicationId;

        IF @BeforeStatus IS NULL
            THROW 51036, ''The application does not exist.'', 1;
        IF @ExpectedRowVersion IS NULL OR @ActualRowVersion <> @ExpectedRowVersion
            THROW 51037, ''The application changed before this update.'', 1;

        UPDATE dbo.Application
        SET
            ApplicationStatus = @NewStatus,
            UpdatedAtUtc = SYSUTCDATETIME()
        WHERE ApplicationId = @ApplicationId;

        SELECT @AfterRowVersion = RowVersion
        FROM dbo.Application
        WHERE ApplicationId = @ApplicationId;

        SELECT @PayloadJson =
        (
            SELECT
                CONVERT(nvarchar(36), @ApplicationId) AS applicationId,
                JSON_QUERY
                (
                    (SELECT @BeforeStatus AS status
                     FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES)
                ) AS [before],
                JSON_QUERY
                (
                    (SELECT @NewStatus AS status
                     FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES)
                ) AS [after]
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        );

        INSERT dbo.AuditEvent
        (
            FellowshipCallId,
            ApplicationId,
            EventType,
            ActorIdentity,
            EntityType,
            EntityId,
            PayloadJson
        )
        VALUES
        (
            @FellowshipCallId,
            @ApplicationId,
            ''APPLICATION_STATUS_CHANGED'',
            @ActorIdentity,
            ''Application'',
            @ApplicationId,
            @PayloadJson
        );

        COMMIT TRANSACTION;

        SELECT
            @ApplicationId AS ApplicationId,
            @NewStatus AS ApplicationStatus,
            @AfterRowVersion AS RowVersion;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.SetUserPreference
    @IdentityKey nvarchar(255),
    @Email nvarchar(320),
    @DisplayName nvarchar(320),
    @Skin varchar(24),
    @InvertColors bit,
    @CompactDensity bit,
    @ReduceMotion bit,
    @ActorIdentity nvarchar(255)
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @UserPreferenceId uniqueidentifier;
    DECLARE @BeforeSkin varchar(24);
    DECLARE @BeforeInvertColors bit;
    DECLARE @BeforeCompactDensity bit;
    DECLARE @BeforeReduceMotion bit;
    DECLARE @PayloadJson nvarchar(max);

    SET @IdentityKey = NULLIF(LTRIM(RTRIM(@IdentityKey)), N'''');
    SET @Email = NULLIF(LTRIM(RTRIM(@Email)), N'''');
    SET @DisplayName = NULLIF(LTRIM(RTRIM(@DisplayName)), N'''');
    SET @ActorIdentity = NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''');

    IF @IdentityKey IS NULL OR @Email IS NULL OR @DisplayName IS NULL
        THROW 51038, ''Identity, email, and display name are required.'', 1;
    IF @ActorIdentity IS NULL
        THROW 51039, ''An actor identity is required.'', 1;
    IF @Skin NOT IN (''default'', ''high-contrast'', ''soft-earth'', ''blue'')
        THROW 51040, ''The requested appearance skin is invalid.'', 1;

    BEGIN TRY
        BEGIN TRANSACTION;

        SELECT
            @UserPreferenceId = UserPreferenceId,
            @BeforeSkin = Skin,
            @BeforeInvertColors = InvertColors,
            @BeforeCompactDensity = CompactDensity,
            @BeforeReduceMotion = ReduceMotion
        FROM dbo.UserPreference WITH (UPDLOCK, HOLDLOCK)
        WHERE IdentityKey = @IdentityKey;

        IF @UserPreferenceId IS NULL
        BEGIN
            SET @UserPreferenceId = NEWID();
            INSERT dbo.UserPreference
            (
                UserPreferenceId,
                IdentityKey,
                Email,
                DisplayName,
                Skin,
                InvertColors,
                CompactDensity,
                ReduceMotion
            )
            VALUES
            (
                @UserPreferenceId,
                @IdentityKey,
                @Email,
                @DisplayName,
                @Skin,
                @InvertColors,
                @CompactDensity,
                @ReduceMotion
            );
        END
        ELSE
        BEGIN
            UPDATE dbo.UserPreference
            SET
                Email = @Email,
                DisplayName = @DisplayName,
                Skin = @Skin,
                InvertColors = @InvertColors,
                CompactDensity = @CompactDensity,
                ReduceMotion = @ReduceMotion,
                UpdatedAtUtc = SYSUTCDATETIME()
            WHERE UserPreferenceId = @UserPreferenceId;
        END;

        SELECT @PayloadJson =
        (
            SELECT
                CONVERT(nvarchar(36), @UserPreferenceId) AS userPreferenceId,
                JSON_QUERY
                (
                    (
                        SELECT
                            @BeforeSkin AS skin,
                            @BeforeInvertColors AS invertColors,
                            @BeforeCompactDensity AS compactDensity,
                            @BeforeReduceMotion AS reduceMotion
                        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES
                    )
                ) AS [before],
                JSON_QUERY
                (
                    (
                        SELECT
                            @Skin AS skin,
                            @InvertColors AS invertColors,
                            @CompactDensity AS compactDensity,
                            @ReduceMotion AS reduceMotion
                        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES
                    )
                ) AS [after]
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        );

        INSERT dbo.AuditEvent
        (
            EventType,
            ActorIdentity,
            EntityType,
            EntityId,
            PayloadJson
        )
        VALUES
        (
            ''USER_PREFERENCE_SET'',
            @ActorIdentity,
            ''UserPreference'',
            @UserPreferenceId,
            @PayloadJson
        );

        COMMIT TRANSACTION;

        SELECT
            UserPreferenceId,
            IdentityKey,
            Email,
            DisplayName,
            Skin,
            InvertColors,
            CompactDensity,
            ReduceMotion,
            UpdatedAtUtc,
            RowVersion
        FROM dbo.UserPreference
        WHERE UserPreferenceId = @UserPreferenceId;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');
