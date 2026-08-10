SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE USER EHFPreferenceProcedureExecutor WITHOUT LOGIN;

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
ALTER TRIGGER dbo.TR_AuditEvent_RejectSensitivePayload
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
ALTER TRIGGER dbo.TR_UserPreference_ProcedureOnly
ON dbo.UserPreference
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF USER_NAME() <> N''EHFPreferenceProcedureExecutor''
        THROW 51033, ''User preferences may be changed only through the approved procedure.'', 1;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.SetUserPreference
    @IdentityKey nvarchar(255),
    @Email nvarchar(320),
    @DisplayName nvarchar(320),
    @Skin varchar(24),
    @InvertColors bit,
    @CompactDensity bit,
    @ReduceMotion bit,
    @ActorIdentity nvarchar(255)
WITH EXECUTE AS ''EHFPreferenceProcedureExecutor''
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

DENY IMPERSONATE ON USER::EHFPreferenceProcedureExecutor TO public;
