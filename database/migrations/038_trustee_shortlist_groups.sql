SET NOCOUNT ON;
SET XACT_ABORT ON;

ALTER TABLE dbo.TrusteeShortlistSelection
    ADD GroupCode char(1) NULL;

ALTER TABLE dbo.TrusteeShortlistSelection
    ADD CONSTRAINT CK_TrusteeShortlistSelection_GroupCode
    CHECK (GroupCode IN ('A', 'B', 'C') OR GroupCode IS NULL);

UPDATE dbo.TrusteeShortlistSelection
SET GroupCode = 'A'
WHERE IsSelected = 1;

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
        N''category'', N''trusteecode'', N''selected'', N''group''
    ) RETURN 0;
    RETURN 1;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.GetInternalShortlistSelections
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

    SELECT selection_row.ApplicationId, selection_row.TrusteeCode, selection_row.GroupCode
    FROM dbo.TrusteeShortlistSelection AS selection_row
    JOIN dbo.Application AS application_row ON application_row.ApplicationId = selection_row.ApplicationId
    JOIN dbo.FellowshipCall AS call_row ON call_row.FellowshipCallId = application_row.FellowshipCallId
    WHERE call_row.CallCode = N''EHF-2026'';
END;
');

EXEC(N'
ALTER PROCEDURE dbo.SetInternalShortlistSelection
    @ApplicationId uniqueidentifier,
    @TrusteeCode varchar(16),
    @GroupCode char(1),
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128),
    @ActorEntraObjectId uniqueidentifier
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @BeforeGroup char(1);
    DECLARE @PayloadJson nvarchar(max);

    IF @ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')
       OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
       OR @ActorEntraObjectId IS NULL
        THROW 54401, ''Administrator or trustee authorization is required.'', 1;
    IF @TrusteeCode NOT IN (''ricky'', ''magda'', ''adriano'')
        THROW 54402, ''The trustee column is invalid.'', 1;
    IF @GroupCode IS NOT NULL AND @GroupCode NOT IN (''A'', ''B'', ''C'')
        THROW 54405, ''The shortlist group is invalid.'', 1;
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
        SELECT @BeforeGroup = GroupCode
        FROM dbo.TrusteeShortlistSelection WITH (UPDLOCK, HOLDLOCK)
        WHERE ApplicationId = @ApplicationId AND TrusteeCode = @TrusteeCode;

        IF @@ROWCOUNT = 0
            INSERT dbo.TrusteeShortlistSelection
                (ApplicationId, TrusteeCode, IsSelected, GroupCode, ModifiedByIdentity)
            VALUES (@ApplicationId, @TrusteeCode, CASE WHEN @GroupCode IS NULL THEN 0 ELSE 1 END, @GroupCode, @ActorIdentity);
        ELSE
            UPDATE dbo.TrusteeShortlistSelection
            SET IsSelected = CASE WHEN @GroupCode IS NULL THEN 0 ELSE 1 END,
                GroupCode = @GroupCode,
                ModifiedByIdentity = @ActorIdentity,
                RecordedAtUtc = SYSUTCDATETIME()
            WHERE ApplicationId = @ApplicationId AND TrusteeCode = @TrusteeCode;

        SELECT @PayloadJson =
        (
            SELECT CONVERT(nvarchar(36), @ApplicationId) AS applicationId,
                   @TrusteeCode AS trusteeCode,
                   JSON_QUERY((SELECT @BeforeGroup AS [group] FOR JSON PATH, WITHOUT_ARRAY_WRAPPER)) AS [before],
                   JSON_QUERY((SELECT @GroupCode AS [group] FOR JSON PATH, WITHOUT_ARRAY_WRAPPER)) AS [after]
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        );
        INSERT dbo.AuditEvent
            (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
        VALUES
            (@ApplicationId, ''SHORTLIST_SELECTION_SET'', @ActorIdentity,
             ''TrusteeShortlistSelection'', @ApplicationId, @PayloadJson);
        COMMIT TRANSACTION;
        SELECT @GroupCode AS [group];
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');
