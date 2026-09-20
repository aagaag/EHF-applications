SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE TABLE dbo.ApplicationPublicationReview
(
    ApplicationPublicationReviewId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicationPublicationReview_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationPublicationId uniqueidentifier NOT NULL,
    ReviewDisposition varchar(32) NOT NULL,
    ResolutionStatus varchar(20) NOT NULL,
    ReviewerIdentity nvarchar(255) NOT NULL,
    ReviewReason nvarchar(2000) NOT NULL,
    EvidenceJson nvarchar(max) NOT NULL,
    RecordedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicationPublicationReview_RecordedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ApplicationPublicationReview PRIMARY KEY (ApplicationPublicationReviewId),
    CONSTRAINT FK_ApplicationPublicationReview_Publication FOREIGN KEY
        (ApplicationPublicationId) REFERENCES dbo.ApplicationPublication (ApplicationPublicationId),
    CONSTRAINT CK_ApplicationPublicationReview_Disposition CHECK
        (ReviewDisposition IN
            ('PUBLISHED', 'ACCEPTED_PREPRINT', 'UNDER_PREPARATION',
             'NON_PUBLICATION', 'PENDING_REVIEW')),
    CONSTRAINT CK_ApplicationPublicationReview_Status CHECK
        (ResolutionStatus IN ('RESOLVED', 'AMBIGUOUS', 'UNRESOLVED')),
    CONSTRAINT CK_ApplicationPublicationReview_Reviewer CHECK
        (LEN(LTRIM(RTRIM(ReviewerIdentity))) > 0),
    CONSTRAINT CK_ApplicationPublicationReview_Reason CHECK
        (LEN(LTRIM(RTRIM(ReviewReason))) > 0),
    CONSTRAINT CK_ApplicationPublicationReview_Evidence CHECK
        (ISJSON(EvidenceJson) = 1 AND DATALENGTH(EvidenceJson) <= 16000)
);

CREATE INDEX IX_ApplicationPublicationReview_Latest
    ON dbo.ApplicationPublicationReview
       (ApplicationPublicationId, RecordedAtUtc DESC, ApplicationPublicationReviewId DESC);

EXEC(N'
CREATE TRIGGER dbo.TR_ApplicationPublicationReview_AppendOnly
ON dbo.ApplicationPublicationReview
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 54080, ''Publication reviews are append-only.'', 1;
END;
');

DROP TRIGGER dbo.TR_ApplicationPublication_NoOverwrite;
EXEC(N'
CREATE TRIGGER dbo.TR_ApplicationPublication_NoOverwrite
ON dbo.ApplicationPublication
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM deleted) AND NOT EXISTS (SELECT 1 FROM inserted)
        THROW 54020, ''Application publications cannot be deleted.'', 1;
    IF EXISTS
    (
        SELECT 1
        FROM deleted AS old_row
        JOIN inserted AS new_row
          ON new_row.ApplicationPublicationId = old_row.ApplicationPublicationId
        WHERE new_row.ApplicationId <> old_row.ApplicationId
           OR new_row.CreatedByImportRunId <> old_row.CreatedByImportRunId
           OR new_row.PublicationIdentitySha256 <> old_row.PublicationIdentitySha256
           OR new_row.ManifestWorkKey <> old_row.ManifestWorkKey
           OR
           (
               new_row.ResolutionStatus <> old_row.ResolutionStatus
               AND NOT
               (
                   old_row.ResolutionStatus IN (''UNRESOLVED'', ''AMBIGUOUS'')
                   AND new_row.ResolutionStatus = ''RESOLVED''
                   AND COALESCE(TRY_CONVERT(bit, SESSION_CONTEXT(N''EHFPublicationPromotion'')), 0) = 1
               )
           )
           OR (old_row.Doi IS NOT NULL AND (new_row.Doi IS NULL OR new_row.Doi <> old_row.Doi))
           OR (old_row.HttpLink IS NOT NULL AND (new_row.HttpLink IS NULL OR new_row.HttpLink <> old_row.HttpLink))
           OR (old_row.AuthorsText IS NOT NULL AND (new_row.AuthorsText IS NULL OR new_row.AuthorsText <> old_row.AuthorsText))
           OR (old_row.Title IS NOT NULL AND (new_row.Title IS NULL OR new_row.Title <> old_row.Title))
           OR (old_row.JournalText IS NOT NULL AND (new_row.JournalText IS NULL OR new_row.JournalText <> old_row.JournalText))
           OR (old_row.VolumeText IS NOT NULL AND (new_row.VolumeText IS NULL OR new_row.VolumeText <> old_row.VolumeText))
           OR (old_row.PagesText IS NOT NULL AND (new_row.PagesText IS NULL OR new_row.PagesText <> old_row.PagesText))
           OR (old_row.PublicationYear IS NOT NULL AND (new_row.PublicationYear IS NULL OR new_row.PublicationYear <> old_row.PublicationYear))
    )
        THROW 54021, ''A non-blank publication value cannot be overwritten or cleared.'', 1;
    UPDATE target_row
       SET Doi = COALESCE(target_row.Doi, new_row.Doi),
           HttpLink = COALESCE(target_row.HttpLink, new_row.HttpLink),
           AuthorsText = COALESCE(target_row.AuthorsText, new_row.AuthorsText),
           Title = COALESCE(target_row.Title, new_row.Title),
           JournalText = COALESCE(target_row.JournalText, new_row.JournalText),
           VolumeText = COALESCE(target_row.VolumeText, new_row.VolumeText),
           PagesText = COALESCE(target_row.PagesText, new_row.PagesText),
           PublicationYear = COALESCE(target_row.PublicationYear, new_row.PublicationYear),
           ResolutionStatus = CASE
               WHEN old_row.ResolutionStatus IN (''UNRESOLVED'', ''AMBIGUOUS'')
                AND new_row.ResolutionStatus = ''RESOLVED''
                AND COALESCE(TRY_CONVERT(bit, SESSION_CONTEXT(N''EHFPublicationPromotion'')), 0) = 1
               THEN ''RESOLVED''
               ELSE target_row.ResolutionStatus
           END,
           UpdatedAtUtc = SYSUTCDATETIME()
    FROM dbo.ApplicationPublication AS target_row
    JOIN inserted AS new_row
      ON new_row.ApplicationPublicationId = target_row.ApplicationPublicationId
    JOIN deleted AS old_row
      ON old_row.ApplicationPublicationId = target_row.ApplicationPublicationId;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.RecordApplicationPublicationReview
    @ApplicationPublicationId uniqueidentifier,
    @ReviewDisposition varchar(32),
    @ReviewerIdentity nvarchar(255),
    @ReviewReason nvarchar(2000),
    @EvidenceJson nvarchar(max)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @ApplicationId uniqueidentifier, @ResolutionStatus varchar(20);
    SELECT @ApplicationId = ApplicationId, @ResolutionStatus = ResolutionStatus
    FROM dbo.ApplicationPublication WITH (UPDLOCK, HOLDLOCK)
    WHERE ApplicationPublicationId = @ApplicationPublicationId;
    IF @ApplicationId IS NULL
        THROW 54081, ''The publication to review does not exist.'', 1;
    IF @ReviewDisposition NOT IN
       (''PUBLISHED'', ''ACCEPTED_PREPRINT'', ''UNDER_PREPARATION'', ''NON_PUBLICATION'', ''PENDING_REVIEW'')
        THROW 54082, ''The publication review disposition is invalid.'', 1;
    IF NULLIF(LTRIM(RTRIM(@ReviewerIdentity)), N'''') IS NULL
       OR NULLIF(LTRIM(RTRIM(@ReviewReason)), N'''') IS NULL
       OR ISJSON(@EvidenceJson) <> 1 OR DATALENGTH(@EvidenceJson) > 16000
        THROW 54083, ''Publication review identity, reason, and JSON evidence are required.'', 1;
    IF @ReviewDisposition = ''PUBLISHED'' AND @ResolutionStatus <> ''RESOLVED''
        THROW 54084, ''Only a resolved record can be included in published-paper statistics.'', 1;

    DECLARE @ReviewId uniqueidentifier = NEWID();
    INSERT dbo.ApplicationPublicationReview
        (ApplicationPublicationReviewId, ApplicationPublicationId, ReviewDisposition,
         ResolutionStatus, ReviewerIdentity, ReviewReason, EvidenceJson)
    VALUES
        (@ReviewId, @ApplicationPublicationId, @ReviewDisposition, @ResolutionStatus,
         LTRIM(RTRIM(@ReviewerIdentity)), LTRIM(RTRIM(@ReviewReason)), @EvidenceJson);

    INSERT dbo.AuditEvent
        (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
    VALUES
        (@ApplicationId, ''PUBLICATION_REVIEW_RECORDED'', LTRIM(RTRIM(@ReviewerIdentity)),
         ''ApplicationPublicationReview'', @ReviewId,
         (SELECT @ApplicationPublicationId AS publicationId,
                 @ReviewDisposition AS disposition,
                 @ResolutionStatus AS resolutionStatus
          FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));
END;
');

EXEC(N'
CREATE PROCEDURE dbo.PromoteApplicationPublication
    @ApplicationPublicationId uniqueidentifier,
    @Doi varchar(255),
    @HttpLink nvarchar(2048) = NULL,
    @AuthorsText nvarchar(max),
    @Title nvarchar(2000),
    @JournalText nvarchar(1000),
    @VolumeText nvarchar(255) = NULL,
    @PagesText nvarchar(255) = NULL,
    @PublicationYear smallint,
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
        THROW 54085, ''The publication to promote does not exist.'', 1;
    IF @PreviousStatus NOT IN (''UNRESOLVED'', ''AMBIGUOUS'')
        THROW 54086, ''Only an unresolved or ambiguous publication can be promoted.'', 1;
    IF @NormalizedDoi IS NULL
       OR NULLIF(LTRIM(RTRIM(@AuthorsText)), N'''') IS NULL
       OR NULLIF(LTRIM(RTRIM(@Title)), N'''') IS NULL
       OR NULLIF(LTRIM(RTRIM(@JournalText)), N'''') IS NULL
       OR @PublicationYear NOT BETWEEN 1600 AND 2200
        THROW 54087, ''Verified DOI, authors, title, journal, and publication year are required for promotion.'', 1;
    IF @ExistingDoi IS NOT NULL AND @ExistingDoi <> @NormalizedDoi
        THROW 54088, ''A promotion cannot replace an existing DOI.'', 1;
    IF ISJSON(@EvidenceJson) <> 1 OR DATALENGTH(@EvidenceJson) > 16000
        THROW 54089, ''Promotion evidence must be valid JSON.'', 1;

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
            @ReviewDisposition=''PUBLISHED'',
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

INSERT dbo.ApplicationPublicationReview
    (ApplicationPublicationId, ReviewDisposition, ResolutionStatus, ReviewerIdentity,
     ReviewReason, EvidenceJson)
SELECT publication_row.ApplicationPublicationId,
       CASE WHEN publication_row.ResolutionStatus = 'RESOLVED'
                  AND publication_row.Doi IS NOT NULL THEN 'PUBLISHED'
            ELSE 'PENDING_REVIEW' END,
       publication_row.ResolutionStatus,
       N'migration:025-publication-review',
       CASE WHEN publication_row.ResolutionStatus = 'RESOLVED'
                  AND publication_row.Doi IS NOT NULL
            THEN N'Backfilled verified publication imported before the review workflow.'
            ELSE N'Backfilled source record awaiting bibliographic classification.' END,
       (SELECT N'025_publication_review_workflow' AS migration,
               publication_row.ManifestWorkKey AS manifestWorkKey,
               publication_row.ResolutionStatus AS previousResolutionStatus
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER)
FROM dbo.ApplicationPublication AS publication_row
WHERE NOT EXISTS
(
    SELECT 1 FROM dbo.ApplicationPublicationReview AS review_row
    WHERE review_row.ApplicationPublicationId = publication_row.ApplicationPublicationId
);

DECLARE @AritraApplicationId uniqueidentifier;
SELECT @AritraApplicationId = application_row.ApplicationId
FROM dbo.Application AS application_row
JOIN dbo.Applicant AS applicant
  ON applicant.ApplicantId = application_row.ApplicantId
WHERE applicant.LegalGivenNames = N'Aritra'
  AND applicant.LegalFamilyName = N'Chowdhury';

IF @AritraApplicationId IS NOT NULL
BEGIN
    DECLARE @PW0105 uniqueidentifier, @PW0106 uniqueidentifier,
            @PW0108 uniqueidentifier, @PW0121 uniqueidentifier,
            @PW0128 uniqueidentifier, @PW0129 uniqueidentifier;
    SELECT @PW0105=ApplicationPublicationId FROM dbo.ApplicationPublication
     WHERE ApplicationId=@AritraApplicationId AND ManifestWorkKey='PW0105';
    SELECT @PW0106=ApplicationPublicationId FROM dbo.ApplicationPublication
     WHERE ApplicationId=@AritraApplicationId AND ManifestWorkKey='PW0106';
    SELECT @PW0108=ApplicationPublicationId FROM dbo.ApplicationPublication
     WHERE ApplicationId=@AritraApplicationId AND ManifestWorkKey='PW0108';
    SELECT @PW0121=ApplicationPublicationId FROM dbo.ApplicationPublication
     WHERE ApplicationId=@AritraApplicationId AND ManifestWorkKey='PW0121';
    SELECT @PW0128=ApplicationPublicationId FROM dbo.ApplicationPublication
     WHERE ApplicationId=@AritraApplicationId AND ManifestWorkKey='PW0128';
    SELECT @PW0129=ApplicationPublicationId FROM dbo.ApplicationPublication
     WHERE ApplicationId=@AritraApplicationId AND ManifestWorkKey='PW0129';

    IF @PW0105 IS NOT NULL EXEC dbo.RecordApplicationPublicationReview
        @ApplicationPublicationId=@PW0105, @ReviewDisposition='NON_PUBLICATION',
        @ReviewerIdentity=N'migration:025-publication-review',
        @ReviewReason=N'The source entry is a dossier heading/legend rather than a publication.',
        @EvidenceJson=N'{"source":"Aritra Chowdhury dossier","classification":"heading or legend"}';
    IF @PW0106 IS NOT NULL EXEC dbo.RecordApplicationPublicationReview
        @ApplicationPublicationId=@PW0106, @ReviewDisposition='ACCEPTED_PREPRINT',
        @ReviewerIdentity=N'migration:025-publication-review',
        @ReviewReason=N'The verified record is a preprint/accepted manuscript, not a published journal paper.',
        @EvidenceJson=N'{"doi":"10.1101/2025.02.23.639383","source":"bioRxiv","classification":"preprint"}';
    IF @PW0128 IS NOT NULL EXEC dbo.RecordApplicationPublicationReview
        @ApplicationPublicationId=@PW0128, @ReviewDisposition='UNDER_PREPARATION',
        @ReviewerIdentity=N'migration:025-publication-review',
        @ReviewReason=N'The applicant marked this entry as under preparation.',
        @EvidenceJson=N'{"source":"Aritra Chowdhury dossier","classification":"under preparation"}';
    IF @PW0129 IS NOT NULL EXEC dbo.RecordApplicationPublicationReview
        @ApplicationPublicationId=@PW0129, @ReviewDisposition='UNDER_PREPARATION',
        @ReviewerIdentity=N'migration:025-publication-review',
        @ReviewReason=N'The applicant marked this entry as under preparation.',
        @EvidenceJson=N'{"source":"Aritra Chowdhury dossier","classification":"under preparation"}';
    IF @PW0108 IS NOT NULL AND EXISTS
       (SELECT 1 FROM dbo.ApplicationPublication WHERE ApplicationPublicationId=@PW0108 AND ResolutionStatus IN ('UNRESOLVED','AMBIGUOUS'))
        EXEC dbo.PromoteApplicationPublication
            @ApplicationPublicationId=@PW0108,
            @Doi='10.1002/advs.202514056',
            @HttpLink=N'https://doi.org/10.1002/advs.202514056',
            @AuthorsText=N'Michael Phillips; Andrea Holla; Magdalena Wojtas; Aritra Chowdhury; Andrea Sottini; Sebastian L. B. König; Natalie Mutter; Nick Lamb; Jonathan Huihui; Monika Lopko; Andrea Soranno; Daniel Nettels; Andrzej Ożyhar; Benjamin Schuler; Kingshuk Ghosh',
            @Title=N'Mapping Charge Interactions in Intrinsically Disordered Proteins',
            @JournalText=N'Advanced Science', @VolumeText=N'13', @PagesText=N'e14056', @PublicationYear=2026,
            @ReviewerIdentity=N'migration:025-publication-review',
            @ReviewReason=N'Promoted after DOI verification; the 2025 online-first date and 2026 issue year describe the same article.',
            @EvidenceJson=N'{"doi":"10.1002/advs.202514056","source":"Wiley Advanced Science","onlineYear":2025,"issueYear":2026}';
    IF @PW0121 IS NOT NULL AND EXISTS
       (SELECT 1 FROM dbo.ApplicationPublication WHERE ApplicationPublicationId=@PW0121 AND ResolutionStatus IN ('UNRESOLVED','AMBIGUOUS'))
        EXEC dbo.PromoteApplicationPublication
            @ApplicationPublicationId=@PW0121,
            @Doi='10.1073/pnas.1704692114',
            @HttpLink=N'https://doi.org/10.1073/pnas.1704692114',
            @AuthorsText=N'Gustavo Fuertes; Niccolò Banterle; Kiersten M. Ruff; Aritra Chowdhury; Davide Mercadante; Christine Koehler; Michael Kachala; Gemma Estrada Girona; Sigrid Milles; Ankur Mishra; Patrick R. Onck; Frauke Gräter; Santiago Esteban-Martín; Rohit V. Pappu; Dmitri I. Svergun; Edward A. Lemke',
            @Title=N'Decoupling of size and shape fluctuations in heteropolymeric sequences reconciles discrepancies in SAXS vs. FRET measurements',
            @JournalText=N'Proceedings of the National Academy of Sciences', @VolumeText=N'114', @PagesText=N'E6342-E6351', @PublicationYear=2017,
            @ReviewerIdentity=N'migration:025-publication-review',
            @ReviewReason=N'Promoted after DOI verification; versus and vs. were normalized before matching.',
            @EvidenceJson=N'{"doi":"10.1073/pnas.1704692114","source":"PubMed","titleNormalization":"versus to vs"}';
END;

EXEC(N'
ALTER PROCEDURE dbo.GetApplicantPreview
    @ApplicationId uniqueidentifier,
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128),
    @EmitResult bit = 1,
    @EmitDrafts bit = 1,
    @EmitPublications bit = 0
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @ActorGroup <> N''EHF-Administrators'' OR LEN(LTRIM(RTRIM(@ActorIdentity))) = 0
        THROW 52810, ''Administrator authorization is required.'', 1;
    IF EXISTS (SELECT 1 FROM dbo.ApplicantSyntheticWorkspace WHERE ApplicationId=@ApplicationId)
        THROW 52910, ''Synthetic workspaces are unavailable to applicant preview.'', 1;
    DECLARE @ProjectionJson nvarchar(max), @ApplicantName nvarchar(401), @ApplicationStatus varchar(20);
    SELECT @ProjectionJson=baseline.ProjectionJson,
           @ApplicantName=COALESCE(NULLIF(JSON_VALUE(identity_draft.DraftJson, ''$.fullName''), N''''),
             NULLIF(JSON_VALUE(baseline.ProjectionJson, ''$.applicant.fullName''), N''''),
             CONCAT(applicant.LegalGivenNames,N'' '',applicant.LegalFamilyName)),
           @ApplicationStatus=application_row.ApplicationStatus
    FROM dbo.ApplicantPortalBaseline AS baseline
    JOIN dbo.Application AS application_row ON application_row.ApplicationId=baseline.ApplicationId
    JOIN dbo.Applicant AS applicant ON applicant.ApplicantId=application_row.ApplicantId
    OUTER APPLY (SELECT TOP (1) DraftJson FROM dbo.ApplicantSectionDraft
                 WHERE ApplicationId=application_row.ApplicationId AND SectionCode=''identity'') AS identity_draft
    WHERE baseline.ApplicationId=@ApplicationId;
    IF @ProjectionJson IS NULL THROW 52811, ''The applicant preview is unavailable.'', 1;
    INSERT dbo.AuditEvent (ApplicationId,EventType,ActorIdentity,EntityType,EntityId,PayloadJson)
    VALUES (@ApplicationId,''APPLICANT_PREVIEW_OPENED'',LTRIM(RTRIM(@ActorIdentity)),''Application'',@ApplicationId,
            (SELECT @ActorGroup AS actorGroup FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));
    IF @EmitResult=1 SELECT @ApplicationId AS ApplicationId,@ApplicantName AS ApplicantName,
       @ApplicationStatus AS ApplicationStatus,@ProjectionJson AS ProjectionJson;
    IF @EmitDrafts=1 SELECT SectionCode,DraftJson FROM dbo.ApplicantSectionDraft
       WHERE ApplicationId=@ApplicationId ORDER BY SectionCode;
    IF @EmitPublications=1
        SELECT publication_row.ApplicationPublicationId, publication_row.AuthorsText,
               publication_row.Title, publication_row.JournalText, publication_row.VolumeText,
               publication_row.PagesText, publication_row.PublicationYear,
               scholar.CitationCount, scholar.CitationStatus, publication_row.Doi,
               openalex.CitationCount AS OpenAlexCitationCount,
               openalex.CitationStatus AS OpenAlexCitationStatus,
               semantic_scholar.CitationCount AS SemanticScholarCitationCount,
               semantic_scholar.CitationStatus AS SemanticScholarCitationStatus,
               publication_row.ResolutionStatus, review_row.ReviewDisposition,
               review_row.ReviewReason, review_row.EvidenceJson,
               source_row.RawCitation, source_row.SourcePage
        FROM dbo.ApplicationPublication AS publication_row
        OUTER APPLY (SELECT TOP (1) CitationCount,CitationStatus FROM dbo.PublicationCitationObservation
          WHERE ApplicationPublicationId=publication_row.ApplicationPublicationId AND SourceCode=''GOOGLE_SCHOLAR''
          ORDER BY CASE WHEN ObservedAtUtc IS NULL THEN 1 ELSE 0 END,ObservedAtUtc DESC,RecordedAtUtc DESC,
                   PublicationCitationObservationId DESC) AS scholar
        OUTER APPLY (SELECT TOP (1) CitationCount,CitationStatus FROM dbo.PublicationCitationObservation
          WHERE ApplicationPublicationId=publication_row.ApplicationPublicationId AND SourceCode=''OPENALEX''
          ORDER BY CASE WHEN ObservedAtUtc IS NULL THEN 1 ELSE 0 END,ObservedAtUtc DESC,RecordedAtUtc DESC,
                   PublicationCitationObservationId DESC) AS openalex
        OUTER APPLY (SELECT TOP (1) CitationCount,CitationStatus FROM dbo.PublicationCitationObservation
          WHERE ApplicationPublicationId=publication_row.ApplicationPublicationId AND SourceCode=''SEMANTIC_SCHOLAR''
          ORDER BY CASE WHEN ObservedAtUtc IS NULL THEN 1 ELSE 0 END,ObservedAtUtc DESC,RecordedAtUtc DESC,
                   PublicationCitationObservationId DESC) AS semantic_scholar
        OUTER APPLY (SELECT TOP (1) ReviewDisposition,ReviewReason,EvidenceJson
          FROM dbo.ApplicationPublicationReview WHERE ApplicationPublicationId=publication_row.ApplicationPublicationId
          ORDER BY RecordedAtUtc DESC,ApplicationPublicationReviewId DESC) AS review_row
        OUTER APPLY (SELECT TOP (1) RawCitation,SourcePage
          FROM dbo.ApplicationPublicationSourceOccurrence WHERE ApplicationPublicationId=publication_row.ApplicationPublicationId
          ORDER BY RecordedAtUtc DESC,ApplicationPublicationSourceOccurrenceId DESC) AS source_row
        WHERE publication_row.ApplicationId=@ApplicationId
        ORDER BY publication_row.PublicationYear DESC, publication_row.Title, publication_row.ApplicationPublicationId;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.GetInternalApplicationMetrics
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    IF @ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')
        THROW 51725, ''The internal metrics role is not authorized.'', 1;
    SELECT
        COALESCE(JSON_VALUE(identity_section.SnapshotJson,''$.fullName''),CONCAT(applicant.LegalGivenNames,N'' '',applicant.LegalFamilyName)) AS ApplicantName,
        COALESCE((SELECT STRING_AGG(JSON_VALUE(degree_row.value,''$.degreeType''),N'', '') WITHIN GROUP (ORDER BY TRY_CONVERT(int,degree_row.[key])) FROM OPENJSON(qualification_section.SnapshotJson,''$.degrees'') AS degree_row),JSON_VALUE(qualification_section.SnapshotJson,''$.degreeCategory''),JSON_VALUE(legacy_section.SnapshotJson,''$.degree'')) AS Degree,
        TRY_CONVERT(decimal(8,2),JSON_VALUE(legacy_section.SnapshotJson,''$.age_observation'')) AS AgeObservation,
        COALESCE(TRY_CONVERT(decimal(8,2),DATEDIFF(day,academic_degree.PhdConferralDate,TRY_CONVERT(date,call_row.ApplicationDeadlineUtc))/365.2425),TRY_CONVERT(decimal(8,2),JSON_VALUE(legacy_section.SnapshotJson,''$.academic_age_observation''))) AS AcademicAgeObservation,
        COALESCE(JSON_VALUE(identity_section.SnapshotJson,''$.gender''),applicant.SelfReportedGender) AS SelfReportedGender,
        COALESCE(TRY_CONVERT(int,JSON_VALUE(publication_section.SnapshotJson,''$.firstAuthorPaperCount'')),bibliometrics.FirstAuthorPaperCount) AS FirstAuthorPaperCount,
        COALESCE(TRY_CONVERT(int,JSON_VALUE(publication_section.SnapshotJson,''$.lastAuthorPaperCount'')),bibliometrics.LastAuthorPaperCount) AS LastAuthorPaperCount,
        COALESCE(TRY_CONVERT(int,JSON_VALUE(publication_section.SnapshotJson,''$.totalPaperCount'')),bibliometrics.TotalPaperCount) AS TotalPaperCount,
        COALESCE(TRY_CONVERT(int,JSON_VALUE(publication_section.SnapshotJson,''$.hIndex'')),TRY_CONVERT(int,JSON_VALUE(legacy_section.SnapshotJson,''$.h_index''))) AS HIndex,
        COALESCE(TRY_CONVERT(bigint,JSON_VALUE(publication_section.SnapshotJson,''$.applicantReportedCitationTotal'')),TRY_CONVERT(bigint,JSON_VALUE(legacy_section.SnapshotJson,''$.total_citations''))) AS TotalCitations,
        COALESCE(JSON_VALUE(publication_section.SnapshotJson,''$.orcid''),JSON_VALUE(legacy_section.SnapshotJson,''$.orcid'')) AS Orcid,
        bibliometrics.GoogleScholarCitationCount AS GoogleScholarCitationCount,
        JSON_VALUE(legacy_section.SnapshotJson,''$.identity_certainty'') AS IdentityCertainty,
        profile_observation.CitationCount AS VerifiedCitationCount,
        profile_observation.SourceCode AS VerifiedCitationSource,
        profile_observation.ProfileUrl AS VerifiedCitationProfileUrl,
        validated_publications.PublishedPaperCount AS ValidatedPublishedPaperCount
    FROM dbo.Application AS application_row
    JOIN dbo.FellowshipCall AS call_row ON call_row.FellowshipCallId=application_row.FellowshipCallId
    JOIN dbo.Applicant AS applicant ON applicant.ApplicantId=application_row.ApplicantId
    LEFT JOIN dbo.Bibliometrics AS bibliometrics ON bibliometrics.ApplicationId=application_row.ApplicationId
    OUTER APPLY (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion WHERE ApplicationId=application_row.ApplicationId AND SectionCode=''identity'' ORDER BY VersionNumber DESC) AS identity_section
    OUTER APPLY (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion WHERE ApplicationId=application_row.ApplicationId AND SectionCode=''qualifications'' ORDER BY VersionNumber DESC) AS qualification_section
    OUTER APPLY (SELECT COALESCE((SELECT MIN(TRY_CONVERT(date,JSON_VALUE(degree_row.value,''$.conferralDate''))) FROM OPENJSON(qualification_section.SnapshotJson,''$.degrees'') AS degree_row WHERE JSON_VALUE(degree_row.value,''$.degreeType'')=''PhD''),CASE WHEN JSON_VALUE(qualification_section.SnapshotJson,''$.degreeCategory'') IN (''PHD'',''MD_PHD'') THEN TRY_CONVERT(date,JSON_VALUE(qualification_section.SnapshotJson,''$.phdDate'')) END,(SELECT MIN(COALESCE(qualification.ConferralDate,qualification.PhdDate)) FROM dbo.Qualification AS qualification WHERE qualification.ApplicationId=application_row.ApplicationId AND qualification.DegreeType IN (''PHD'',''MD_PHD''))) AS PhdConferralDate) AS academic_degree
    OUTER APPLY (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion WHERE ApplicationId=application_row.ApplicationId AND SectionCode=''publications'' ORDER BY VersionNumber DESC) AS publication_section
    OUTER APPLY (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion WHERE ApplicationId=application_row.ApplicationId AND SectionCode=''LEGACY_REGISTER_OBSERVATIONS'' ORDER BY VersionNumber DESC) AS legacy_section
    OUTER APPLY (SELECT TOP (1) CitationCount,SourceCode,ProfileUrl FROM dbo.ApplicantCitationProfileObservation WHERE ApplicationId=application_row.ApplicationId ORDER BY ObservedAtUtc DESC,RecordedAtUtc DESC,ApplicantCitationProfileObservationId DESC) AS profile_observation
    OUTER APPLY (SELECT COUNT_BIG(*) AS PublishedPaperCount FROM dbo.ApplicationPublication AS publication_row
        OUTER APPLY (SELECT TOP (1) ReviewDisposition FROM dbo.ApplicationPublicationReview WHERE ApplicationPublicationId=publication_row.ApplicationPublicationId ORDER BY RecordedAtUtc DESC,ApplicationPublicationReviewId DESC) AS latest_review
        WHERE publication_row.ApplicationId=application_row.ApplicationId AND publication_row.ResolutionStatus=''RESOLVED'' AND latest_review.ReviewDisposition=''PUBLISHED'') AS validated_publications
    WHERE call_row.CallCode=N''EHF-2026''
      AND NOT EXISTS (SELECT 1 FROM dbo.ApplicantSyntheticWorkspace WHERE ApplicationId=application_row.ApplicationId)
    ORDER BY applicant.LegalFamilyName,applicant.LegalGivenNames;
END;
');

GRANT EXECUTE ON dbo.GetApplicantPreview TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetInternalApplicationMetrics TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicationPublicationReview TO EHFApplicationRuntime;
