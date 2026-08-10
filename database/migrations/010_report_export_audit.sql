SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE USER EHFReportExportAuditExecutor WITHOUT LOGIN;

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
        N''before'', N''after'',
        N''applicationid'', N''applicantid'', N''callid'',
        N''documentid'', N''requestid'', N''userpreferenceid'',
        N''status'', N''skin'', N''invertcolors'',
        N''compactdensity'', N''reducemotion'',
        N''actorgroup'', N''rowcount'', N''format'', N''outcome'', N''failurestage''
    )
        RETURN 0;

    RETURN 1;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.RecordReportExportAudit
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(100),
    @RowCount int,
    @Outcome nvarchar(20),
    @FailureStage nvarchar(80) = NULL
WITH EXECUTE AS ''EHFReportExportAuditExecutor''
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @ExportId uniqueidentifier = NEWID();
    DECLARE @PayloadJson nvarchar(max);

    SET @ActorIdentity = NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''');
    SET @ActorGroup = NULLIF(LTRIM(RTRIM(@ActorGroup)), N'''');
    SET @Outcome = NULLIF(LTRIM(RTRIM(@Outcome)), N'''');
    SET @FailureStage = NULLIF(LTRIM(RTRIM(@FailureStage)), N'''');

    IF @ActorIdentity IS NULL OR LEN(@ActorIdentity) > 255
        THROW 51900, ''A valid actor identity is required.'', 1;
    IF @ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')
        THROW 51901, ''The report actor group is invalid.'', 1;
    IF @RowCount IS NULL OR @RowCount < 0 OR @RowCount > 10000
        THROW 51902, ''The report row count is invalid.'', 1;
    IF @Outcome NOT IN (N''COMPLETED'', N''FAILED'')
        THROW 51903, ''The report outcome is invalid.'', 1;
    IF @Outcome = N''COMPLETED'' AND @FailureStage IS NOT NULL
        THROW 51904, ''A completed export cannot have a failure stage.'', 1;
    IF @Outcome = N''FAILED'' AND COALESCE(@FailureStage, N'''') <> N''workbook-generation''
        THROW 51905, ''The report failure stage is invalid.'', 1;

    SELECT @PayloadJson =
    (
        SELECT
            @ActorGroup AS actorGroup,
            @RowCount AS rowCount,
            N''XLSX'' AS format,
            @Outcome AS outcome,
            @FailureStage AS failureStage
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES
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
        CASE @Outcome
            WHEN N''COMPLETED'' THEN ''REPORT_EXPORT_COMPLETED''
            ELSE ''REPORT_EXPORT_FAILED''
        END,
        @ActorIdentity,
        ''ReportExport'',
        @ExportId,
        @PayloadJson
    );
END;
');

GRANT INSERT ON dbo.AuditEvent TO EHFReportExportAuditExecutor;
GRANT EXECUTE ON dbo.RecordReportExportAudit TO EHFApplicationRuntime;
DENY IMPERSONATE ON USER::EHFReportExportAuditExecutor TO EHFApplicationRuntime;
DENY IMPERSONATE ON USER::EHFReportExportAuditExecutor TO public;
