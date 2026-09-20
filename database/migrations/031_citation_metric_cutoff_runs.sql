SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE TABLE dbo.CitationMetricCutoffRun
(
    CitationMetricCutoffRunId uniqueidentifier NOT NULL
        CONSTRAINT PK_CitationMetricCutoffRun PRIMARY KEY
        CONSTRAINT DF_CitationMetricCutoffRun_Id DEFAULT NEWSEQUENTIALID(),
    FellowshipCallId uniqueidentifier NOT NULL,
    ImportRunId uniqueidentifier NOT NULL,
    SourceCode varchar(40) NOT NULL,
    EligibleWorkCount int NOT NULL,
    ObservedWorkCount int NOT NULL,
    NotFoundWorkCount int NOT NULL,
    ObservedAtUtc datetime2(7) NOT NULL,
    ActivatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_CitationMetricCutoffRun_ActivatedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_CitationMetricCutoffRun_Call FOREIGN KEY (FellowshipCallId)
        REFERENCES dbo.FellowshipCall(FellowshipCallId),
    CONSTRAINT FK_CitationMetricCutoffRun_Import FOREIGN KEY (ImportRunId)
        REFERENCES dbo.ImportRun(ImportRunId),
    CONSTRAINT UQ_CitationMetricCutoffRun_Import UNIQUE (ImportRunId),
    CONSTRAINT CK_CitationMetricCutoffRun_Source CHECK
        (SourceCode IN ('OPENALEX', 'SEMANTIC_SCHOLAR')),
    CONSTRAINT CK_CitationMetricCutoffRun_Counts CHECK
        (EligibleWorkCount > 0 AND ObservedWorkCount = EligibleWorkCount
         AND NotFoundWorkCount = 0)
);

CREATE INDEX IX_CitationMetricCutoffRun_Active
    ON dbo.CitationMetricCutoffRun(FellowshipCallId, ActivatedAtUtc DESC,
                                   CitationMetricCutoffRunId DESC);

EXEC(N'
CREATE TRIGGER dbo.TR_CitationMetricCutoffRun_AppendOnly
ON dbo.CitationMetricCutoffRun
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    THROW 53100, ''Citation metric cutoff runs are append-only.'', 1;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ActivateCitationMetricCutoffRun
    @ImportRunId uniqueidentifier
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @FellowshipCallId uniqueidentifier,
            @SourceCode varchar(40),
            @EligibleWorkCount int,
            @ObservedWorkCount int,
            @NotFoundWorkCount int,
            @CutoffAtUtc datetime2(7);

    SELECT @FellowshipCallId = import_row.FellowshipCallId
    FROM dbo.ImportRun AS import_row
    JOIN dbo.FellowshipCall AS call_row
      ON call_row.FellowshipCallId = import_row.FellowshipCallId
    WHERE import_row.ImportRunId = @ImportRunId
      AND import_row.RunStatus = ''COMPLETED''
      AND call_row.CallCode = N''EHF-2026'';
    IF @FellowshipCallId IS NULL
        THROW 53101, ''A completed EHF-2026 citation import run is required.'', 1;

    DECLARE @Eligible TABLE
    (
        ApplicationPublicationId uniqueidentifier NOT NULL PRIMARY KEY
    );
    INSERT @Eligible (ApplicationPublicationId)
    SELECT publication_row.ApplicationPublicationId
    FROM dbo.ApplicationPublication AS publication_row
    JOIN dbo.Application AS application_row
      ON application_row.ApplicationId = publication_row.ApplicationId
    OUTER APPLY
    (
        SELECT TOP (1) review_row.ReviewDisposition
        FROM dbo.ApplicationPublicationReview AS review_row
        WHERE review_row.ApplicationPublicationId = publication_row.ApplicationPublicationId
        ORDER BY review_row.RecordedAtUtc DESC,
                 review_row.ApplicationPublicationReviewId DESC
    ) AS latest_review
    WHERE application_row.FellowshipCallId = @FellowshipCallId
      AND publication_row.ResolutionStatus = ''RESOLVED''
      AND latest_review.ReviewDisposition = ''PUBLISHED'';

    SELECT @EligibleWorkCount = COUNT(*) FROM @Eligible;
    IF @EligibleWorkCount = 0
        THROW 53102, ''The citation cutoff has no eligible published works.'', 1;
    IF EXISTS
    (
        SELECT 1
        FROM @Eligible AS eligible
        OUTER APPLY
        (
            SELECT COUNT(*) AS ObservationCount
            FROM dbo.PublicationCitationObservation AS observation
            WHERE observation.ImportRunId = @ImportRunId
              AND observation.ApplicationPublicationId = eligible.ApplicationPublicationId
        ) AS observed_row
        WHERE observed_row.ObservationCount <> 1
    )
        THROW 53103, ''The citation cutoff is incomplete or has duplicate observations.'', 1;

    SELECT @SourceCode = MIN(observation.SourceCode),
           @ObservedWorkCount = COUNT(CASE WHEN observation.CitationStatus=''OBSERVED'' THEN 1 END),
           @NotFoundWorkCount = COUNT(CASE WHEN observation.CitationStatus<>''OBSERVED'' THEN 1 END),
           @CutoffAtUtc = MAX(observation.ObservedAtUtc)
    FROM dbo.PublicationCitationObservation AS observation
    JOIN @Eligible AS eligible
      ON eligible.ApplicationPublicationId = observation.ApplicationPublicationId
    WHERE observation.ImportRunId = @ImportRunId;

    IF (SELECT COUNT(DISTINCT observation.SourceCode)
        FROM dbo.PublicationCitationObservation AS observation
        JOIN @Eligible AS eligible
          ON eligible.ApplicationPublicationId = observation.ApplicationPublicationId
        WHERE observation.ImportRunId = @ImportRunId) <> 1
        THROW 53104, ''The citation cutoff has mixed sources.'', 1;
    IF @ObservedWorkCount <> @EligibleWorkCount OR @NotFoundWorkCount <> 0
        THROW 53105, ''The citation cutoff is incomplete.'', 1;
    IF @SourceCode NOT IN (''OPENALEX'', ''SEMANTIC_SCHOLAR'') OR @CutoffAtUtc IS NULL
        THROW 53106, ''The citation cutoff source evidence is invalid.'', 1;

    IF EXISTS (SELECT 1 FROM dbo.CitationMetricCutoffRun WHERE ImportRunId = @ImportRunId)
        RETURN;

    INSERT dbo.CitationMetricCutoffRun
        (FellowshipCallId, ImportRunId, SourceCode, EligibleWorkCount,
         ObservedWorkCount, NotFoundWorkCount, ObservedAtUtc)
    VALUES
        (@FellowshipCallId, @ImportRunId, @SourceCode, @EligibleWorkCount,
         @ObservedWorkCount, @NotFoundWorkCount, @CutoffAtUtc);
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
        NULL AS TotalCitations, NULL AS Orcid, NULL AS GoogleScholarCitationCount, NULL AS IdentityCertainty,
        CASE WHEN cutoff.CitationMetricCutoffRunId IS NULL THEN NULL ELSE metric.CitationCount END AS VerifiedCitationCount,
        cutoff.SourceCode AS VerifiedCitationSource,
        NULL AS VerifiedCitationProfileUrl,
        metric.PublishedPaperCount AS ValidatedPublishedPaperCount,
        CONVERT(varchar(36),application_row.ApplicationId) AS ApplicationId,
        CONCAT(N''EHF-2026-'',RIGHT(N''000''+CONVERT(nvarchar(10),ROW_NUMBER() OVER (ORDER BY applicant.LegalFamilyName,applicant.LegalGivenNames,application_row.ApplicationId)),3)) AS ApplicationNumber
    FROM dbo.Application AS application_row
    JOIN dbo.FellowshipCall AS call_row ON call_row.FellowshipCallId=application_row.FellowshipCallId
    JOIN dbo.Applicant AS applicant ON applicant.ApplicantId=application_row.ApplicantId
    LEFT JOIN dbo.Bibliometrics AS bibliometrics ON bibliometrics.ApplicationId=application_row.ApplicationId
    OUTER APPLY (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion WHERE ApplicationId=application_row.ApplicationId AND SectionCode=''identity'' ORDER BY VersionNumber DESC) AS identity_section
    OUTER APPLY (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion WHERE ApplicationId=application_row.ApplicationId AND SectionCode=''qualifications'' ORDER BY VersionNumber DESC) AS qualification_section
    OUTER APPLY (SELECT COALESCE((SELECT MIN(TRY_CONVERT(date,JSON_VALUE(degree_row.value,''$.conferralDate''))) FROM OPENJSON(qualification_section.SnapshotJson,''$.degrees'') AS degree_row WHERE JSON_VALUE(degree_row.value,''$.degreeType'')=''PhD''),CASE WHEN JSON_VALUE(qualification_section.SnapshotJson,''$.degreeCategory'') IN (''PHD'',''MD_PHD'') THEN TRY_CONVERT(date,JSON_VALUE(qualification_section.SnapshotJson,''$.phdDate'')) END,(SELECT MIN(COALESCE(qualification.ConferralDate,qualification.PhdDate)) FROM dbo.Qualification AS qualification WHERE qualification.ApplicationId=application_row.ApplicationId AND qualification.DegreeType IN (''PHD'',''MD_PHD''))) AS PhdConferralDate) AS academic_degree
    OUTER APPLY (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion WHERE ApplicationId=application_row.ApplicationId AND SectionCode=''publications'' ORDER BY VersionNumber DESC) AS publication_section
    OUTER APPLY (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion WHERE ApplicationId=application_row.ApplicationId AND SectionCode=''LEGACY_REGISTER_OBSERVATIONS'' ORDER BY VersionNumber DESC) AS legacy_section
    OUTER APPLY (SELECT TOP (1) cutoff_row.* FROM dbo.CitationMetricCutoffRun AS cutoff_row WHERE cutoff_row.FellowshipCallId=call_row.FellowshipCallId ORDER BY cutoff_row.ActivatedAtUtc DESC,cutoff_row.CitationMetricCutoffRunId DESC) AS cutoff
    OUTER APPLY (SELECT SUM(observation.CitationCount) AS CitationCount, COUNT_BIG(*) AS PublishedPaperCount FROM dbo.ApplicationPublication AS publication_row OUTER APPLY (SELECT TOP (1) review_row.ReviewDisposition FROM dbo.ApplicationPublicationReview AS review_row WHERE review_row.ApplicationPublicationId=publication_row.ApplicationPublicationId ORDER BY review_row.RecordedAtUtc DESC,review_row.ApplicationPublicationReviewId DESC) AS latest_review JOIN dbo.PublicationCitationObservation AS observation ON observation.ApplicationPublicationId=publication_row.ApplicationPublicationId AND observation.ImportRunId=cutoff.ImportRunId AND observation.SourceCode=cutoff.SourceCode AND observation.CitationStatus=''OBSERVED'' WHERE publication_row.ApplicationId=application_row.ApplicationId AND publication_row.ResolutionStatus=''RESOLVED'' AND latest_review.ReviewDisposition=''PUBLISHED'') AS metric
    WHERE call_row.CallCode=N''EHF-2026''
      AND NOT EXISTS (SELECT 1 FROM dbo.ApplicantSyntheticWorkspace WHERE ApplicationId=application_row.ApplicationId)
    ORDER BY applicant.LegalFamilyName,applicant.LegalGivenNames,application_row.ApplicationId;
END;
');

DENY SELECT, INSERT, UPDATE, DELETE ON dbo.CitationMetricCutoffRun TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.ActivateCitationMetricCutoffRun TO EHFApplicationRuntime;
