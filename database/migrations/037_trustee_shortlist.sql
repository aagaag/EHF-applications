SET NOCOUNT ON;
SET XACT_ABORT ON;

EXEC(N'
ALTER FUNCTION dbo.IsAuditPayloadKeyProhibited
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
        N''before'', N''after'', N''applicationid'', N''applicantid'', N''callid'',
        N''documentid'', N''requestid'', N''userpreferenceid'', N''status'', N''skin'',
        N''invertcolors'', N''compactdensity'', N''reducemotion'', N''actorgroup'',
        N''rowcount'', N''format'', N''outcome'', N''failurestage'', N''purpose'',
        N''category'', N''trusteecode'', N''selected''
    ) RETURN 0;
    RETURN 1;
END;
');

CREATE TABLE dbo.ShortlistTrustee
(
    TrusteeCode varchar(16) NOT NULL CONSTRAINT PK_ShortlistTrustee PRIMARY KEY,
    DisplayName nvarchar(80) NOT NULL,
    ActorEntraObjectId uniqueidentifier NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL CONSTRAINT DF_ShortlistTrustee_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_ShortlistTrustee_ActorEntraObjectId UNIQUE (ActorEntraObjectId),
    CONSTRAINT CK_ShortlistTrustee_Code CHECK (TrusteeCode IN ('ricky', 'magda', 'adriano'))
);

INSERT dbo.ShortlistTrustee (TrusteeCode, DisplayName, ActorEntraObjectId)
VALUES
    ('ricky', N'Ricky', '7747ffa7-5193-4cc8-9221-08a1dd24b026'),
    ('magda', N'Magda', '09d14671-38e1-4763-8d67-512c9787d379'),
    ('adriano', N'Adriano', 'd5c5fb6a-f9c3-456c-97b1-20b450647f8c');

CREATE TABLE dbo.TrusteeShortlistSelection
(
    ApplicationId uniqueidentifier NOT NULL,
    TrusteeCode varchar(16) NOT NULL,
    IsSelected bit NOT NULL,
    ModifiedByIdentity nvarchar(255) NOT NULL,
    RecordedAtUtc datetime2(7) NOT NULL CONSTRAINT DF_TrusteeShortlistSelection_RecordedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_TrusteeShortlistSelection PRIMARY KEY (ApplicationId, TrusteeCode),
    CONSTRAINT FK_TrusteeShortlistSelection_Application FOREIGN KEY (ApplicationId) REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT FK_TrusteeShortlistSelection_Trustee FOREIGN KEY (TrusteeCode) REFERENCES dbo.ShortlistTrustee (TrusteeCode),
    CONSTRAINT CK_TrusteeShortlistSelection_Actor CHECK (LEN(ModifiedByIdentity) > 0)
);

EXEC(N'
CREATE PROCEDURE dbo.GetInternalShortlistSelections
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128),
    @ActorEntraObjectId uniqueidentifier
AS
BEGIN
    SET NOCOUNT ON;
    IF @ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')
       OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
       OR @ActorEntraObjectId IS NULL
        THROW 54400, ''Administrator or trustee authorization is required.'', 1;

    SELECT selection_row.ApplicationId, selection_row.TrusteeCode, selection_row.IsSelected
    FROM dbo.TrusteeShortlistSelection AS selection_row
    JOIN dbo.Application AS application_row ON application_row.ApplicationId = selection_row.ApplicationId
    JOIN dbo.FellowshipCall AS call_row ON call_row.FellowshipCallId = application_row.FellowshipCallId
    WHERE call_row.CallCode = N''EHF-2026'';
END;
');

EXEC(N'
CREATE PROCEDURE dbo.SetInternalShortlistSelection
    @ApplicationId uniqueidentifier,
    @TrusteeCode varchar(16),
    @IsSelected bit,
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128),
    @ActorEntraObjectId uniqueidentifier
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @BeforeSelected bit = 0;
    DECLARE @PayloadJson nvarchar(max);

    IF @ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')
       OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
       OR @ActorEntraObjectId IS NULL
        THROW 54401, ''Administrator or trustee authorization is required.'', 1;
    IF @TrusteeCode NOT IN (''ricky'', ''magda'', ''adriano'')
        THROW 54402, ''The trustee column is invalid.'', 1;
    IF NOT EXISTS
    (
        SELECT 1 FROM dbo.ShortlistTrustee
        WHERE ActorEntraObjectId = @ActorEntraObjectId
          AND TrusteeCode = @TrusteeCode
    )
        THROW 54403, ''The signed-in identity does not own this trustee column.'', 1;
    IF NOT EXISTS
    (
        SELECT 1 FROM dbo.Application AS application_row
        JOIN dbo.FellowshipCall AS call_row ON call_row.FellowshipCallId = application_row.FellowshipCallId
        WHERE application_row.ApplicationId = @ApplicationId AND call_row.CallCode = N''EHF-2026''
    )
        THROW 54404, ''The application is unavailable.'', 1;

    BEGIN TRY
        BEGIN TRANSACTION;
        SELECT @BeforeSelected = IsSelected
        FROM dbo.TrusteeShortlistSelection WITH (UPDLOCK, HOLDLOCK)
        WHERE ApplicationId = @ApplicationId AND TrusteeCode = @TrusteeCode;

        IF @@ROWCOUNT = 0
            INSERT dbo.TrusteeShortlistSelection
                (ApplicationId, TrusteeCode, IsSelected, ModifiedByIdentity)
            VALUES (@ApplicationId, @TrusteeCode, @IsSelected, @ActorIdentity);
        ELSE
            UPDATE dbo.TrusteeShortlistSelection
            SET IsSelected = @IsSelected,
                ModifiedByIdentity = @ActorIdentity,
                RecordedAtUtc = SYSUTCDATETIME()
            WHERE ApplicationId = @ApplicationId AND TrusteeCode = @TrusteeCode;

        SELECT @PayloadJson =
        (
            SELECT CONVERT(nvarchar(36), @ApplicationId) AS applicationId,
                   @TrusteeCode AS trusteeCode,
                   JSON_QUERY((SELECT @BeforeSelected AS selected FOR JSON PATH, WITHOUT_ARRAY_WRAPPER)) AS [before],
                   JSON_QUERY((SELECT @IsSelected AS selected FOR JSON PATH, WITHOUT_ARRAY_WRAPPER)) AS [after]
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        );
        INSERT dbo.AuditEvent
            (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
        VALUES
            (@ApplicationId, ''SHORTLIST_SELECTION_SET'', @ActorIdentity,
             ''TrusteeShortlistSelection'', @ApplicationId, @PayloadJson);
        COMMIT TRANSACTION;
        SELECT @IsSelected AS IsSelected;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

GRANT EXECUTE ON dbo.GetInternalShortlistSelections TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.SetInternalShortlistSelection TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ShortlistTrustee TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.TrusteeShortlistSelection TO EHFApplicationRuntime;
