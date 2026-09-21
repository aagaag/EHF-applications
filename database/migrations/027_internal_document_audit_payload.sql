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
        N''before'', N''after'',
        N''applicationid'', N''applicantid'', N''callid'',
        N''documentid'', N''requestid'', N''userpreferenceid'',
        N''status'', N''skin'', N''invertcolors'',
        N''compactdensity'', N''reducemotion'',
        N''actorgroup'', N''rowcount'', N''format'', N''outcome'', N''failurestage'',
        N''purpose''
    )
        RETURN 0;

    RETURN 1;
END;
');
