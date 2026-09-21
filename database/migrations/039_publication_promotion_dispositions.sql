SET NOCOUNT ON;
SET XACT_ABORT ON;

EXEC(N'
ALTER PROCEDURE dbo.PromoteApplicationPublication
    @ApplicationPublicationId uniqueidentifier,
    @Doi varchar(255),
    @HttpLink nvarchar(2048) = NULL,
    @AuthorsText nvarchar(max),
    @Title nvarchar(2000),
    @JournalText nvarchar(1000),
    @VolumeText nvarchar(255) = NULL,
    @PagesText nvarchar(255) = NULL,
    @PublicationYear smallint,
    @ReviewDisposition varchar(32) = ''PUBLISHED'',
    @ReviewerIdentity nvarchar(255),
    @ReviewReason nvarchar(2000),
    @EvidenceJson nvarchar(max)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @PreviousStatus varchar(20), @ExistingDoi varchar(255),
            @NormalizedDoi varchar(255) = LOWER(NULLIF(LTRIM(RTRIM(@Doi)), ''''));
    SELECT @PreviousStatus = ResolutionStatus, @ExistingDoi = Doi
    FROM dbo.ApplicationPublication WITH (UPDLOCK, HOLDLOCK)
    WHERE ApplicationPublicationId = @ApplicationPublicationId;
    IF @PreviousStatus IS NULL
        THROW 54441, ''The publication to promote does not exist.'', 1;
    IF @PreviousStatus NOT IN (''UNRESOLVED'', ''AMBIGUOUS'')
        THROW 54442, ''Only an unresolved or ambiguous publication can be promoted.'', 1;
    IF @ReviewDisposition NOT IN
       (''PUBLISHED'', ''ACCEPTED_PREPRINT'', ''UNDER_PREPARATION'', ''NON_PUBLICATION'', ''PENDING_REVIEW'')
        THROW 54443, ''The publication promotion disposition is invalid.'', 1;
    IF @NormalizedDoi IS NULL
       OR NULLIF(LTRIM(RTRIM(@AuthorsText)), N'''') IS NULL
       OR NULLIF(LTRIM(RTRIM(@Title)), N'''') IS NULL
       OR NULLIF(LTRIM(RTRIM(@JournalText)), N'''') IS NULL
       OR @PublicationYear NOT BETWEEN 1600 AND 2200
        THROW 54444, ''Verified DOI, authors, title, journal, and publication year are required for promotion.'', 1;
    IF @ExistingDoi IS NOT NULL AND @ExistingDoi <> @NormalizedDoi
        THROW 54445, ''A promotion cannot replace an existing DOI.'', 1;
    IF ISJSON(@EvidenceJson) <> 1 OR DATALENGTH(@EvidenceJson) > 16000
        THROW 54446, ''Promotion evidence must be valid JSON.'', 1;

    BEGIN TRY
        BEGIN TRANSACTION;
        EXEC sys.sp_set_session_context @key=N''EHFPublicationPromotion'', @value=1;
        UPDATE dbo.ApplicationPublication
           SET Doi = COALESCE(Doi, @NormalizedDoi),
               HttpLink = COALESCE(HttpLink, @HttpLink),
               AuthorsText = COALESCE(AuthorsText, @AuthorsText),
               Title = COALESCE(Title, @Title),
               JournalText = COALESCE(JournalText, @JournalText),
               VolumeText = COALESCE(VolumeText, @VolumeText),
               PagesText = COALESCE(PagesText, @PagesText),
               PublicationYear = COALESCE(PublicationYear, @PublicationYear),
               ResolutionStatus = ''RESOLVED''
         WHERE ApplicationPublicationId = @ApplicationPublicationId;
        EXEC sys.sp_set_session_context @key=N''EHFPublicationPromotion'', @value=NULL;
        EXEC dbo.RecordApplicationPublicationReview
            @ApplicationPublicationId=@ApplicationPublicationId,
            @ReviewDisposition=@ReviewDisposition,
            @ReviewerIdentity=@ReviewerIdentity,
            @ReviewReason=@ReviewReason,
            @EvidenceJson=@EvidenceJson;
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        EXEC sys.sp_set_session_context @key=N''EHFPublicationPromotion'', @value=NULL;
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');
