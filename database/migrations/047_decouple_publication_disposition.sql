SET NOCOUNT ON;
SET XACT_ABORT ON;

-- DOI resolution is independent of publication disposition. A complete bibliographic
-- record can be PUBLISHED even when no DOI exists or an external resolver finds none.
EXEC(N'
ALTER PROCEDURE dbo.RecordApplicationPublicationReview
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
        THROW 54701, ''The publication to review does not exist.'', 1;
    IF @ReviewDisposition NOT IN
       (''PUBLISHED'', ''ACCEPTED_PREPRINT'', ''UNDER_PREPARATION'', ''NON_PUBLICATION'', ''PENDING_REVIEW'')
        THROW 54702, ''The publication review disposition is invalid.'', 1;
    IF NULLIF(LTRIM(RTRIM(@ReviewerIdentity)), N'''') IS NULL
       OR NULLIF(LTRIM(RTRIM(@ReviewReason)), N'''') IS NULL
       OR ISJSON(@EvidenceJson) <> 1 OR DATALENGTH(@EvidenceJson) > 16000
        THROW 54703, ''Publication review identity, reason, and JSON evidence are required.'', 1;

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
         (SELECT @ReviewDisposition AS outcome,
                 @ResolutionStatus AS status
          FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));
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
        CASE WHEN cutoff.CitationMetricCutoffRunId IS NULL THEN NULL ELSE CONVERT(int,citation_metric.HIndex) END AS HIndex,
        NULL AS TotalCitations, NULL AS Orcid, NULL AS GoogleScholarCitationCount, NULL AS IdentityCertainty,
        CASE WHEN cutoff.CitationMetricCutoffRunId IS NULL THEN NULL ELSE citation_metric.CitationCount END AS VerifiedCitationCount,
        cutoff.SourceCode AS VerifiedCitationSource,
        NULL AS VerifiedCitationProfileUrl,
        status_metric.PublishedPaperCount AS ValidatedPublishedPaperCount,
        status_metric.PreprintPaperCount AS ValidatedPreprintPaperCount,
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
    OUTER APPLY
    (
        SELECT COUNT_BIG(CASE WHEN latest_review.ReviewDisposition=''PUBLISHED'' THEN 1 END) AS PublishedPaperCount,
               COUNT_BIG(CASE WHEN latest_review.ReviewDisposition=''ACCEPTED_PREPRINT'' THEN 1 END) AS PreprintPaperCount
        FROM dbo.ApplicationPublication AS publication_row
        OUTER APPLY (SELECT TOP (1) review_row.ReviewDisposition FROM dbo.ApplicationPublicationReview AS review_row WHERE review_row.ApplicationPublicationId=publication_row.ApplicationPublicationId ORDER BY review_row.RecordedAtUtc DESC,review_row.ApplicationPublicationReviewId DESC) AS latest_review
        WHERE publication_row.ApplicationId=application_row.ApplicationId
    ) AS status_metric
    OUTER APPLY
    (
        SELECT COALESCE(SUM(ranked.CitationCount),CONVERT(bigint,0)) AS CitationCount,
               COALESCE(MAX(CASE WHEN ranked.CitationCount >= ranked.CitationRank THEN ranked.CitationRank ELSE CONVERT(bigint,0) END),CONVERT(bigint,0)) AS HIndex
        FROM
        (
            SELECT observation.CitationCount,
                   ROW_NUMBER() OVER (ORDER BY observation.CitationCount DESC,publication_row.ApplicationPublicationId) AS CitationRank
            FROM dbo.ApplicationPublication AS publication_row
            OUTER APPLY (SELECT TOP (1) review_row.ReviewDisposition FROM dbo.ApplicationPublicationReview AS review_row WHERE review_row.ApplicationPublicationId=publication_row.ApplicationPublicationId ORDER BY review_row.RecordedAtUtc DESC,review_row.ApplicationPublicationReviewId DESC) AS latest_review
            JOIN dbo.PublicationCitationObservation AS observation ON observation.ApplicationPublicationId=publication_row.ApplicationPublicationId AND observation.ImportRunId=cutoff.ImportRunId AND observation.SourceCode=cutoff.SourceCode AND observation.CitationStatus=''OBSERVED''
            WHERE publication_row.ApplicationId=application_row.ApplicationId
              AND publication_row.ResolutionStatus=''RESOLVED''
              AND latest_review.ReviewDisposition=''PUBLISHED''
        ) AS ranked
    ) AS citation_metric
    WHERE call_row.CallCode=N''EHF-2026''
      AND NOT EXISTS (SELECT 1 FROM dbo.ApplicantSyntheticWorkspace WHERE ApplicationId=application_row.ApplicationId)
    ORDER BY applicant.LegalFamilyName,applicant.LegalGivenNames,application_row.ApplicationId;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.GetInternalApplicantMetricDetail
    @ApplicationId uniqueidentifier,
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    IF @ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')
        THROW 51725, ''The internal metrics role is not authorized.'', 1;

    ;WITH ranked AS
    (
        SELECT application_row.ApplicationId,applicant.LegalGivenNames,applicant.LegalFamilyName,
               ROW_NUMBER() OVER (ORDER BY applicant.LegalFamilyName,applicant.LegalGivenNames,application_row.ApplicationId) AS ApplicationNumber
        FROM dbo.Application AS application_row
        JOIN dbo.FellowshipCall AS call_row ON call_row.FellowshipCallId=application_row.FellowshipCallId
        JOIN dbo.Applicant AS applicant ON applicant.ApplicantId=application_row.ApplicantId
        WHERE call_row.CallCode=N''EHF-2026''
          AND NOT EXISTS (SELECT 1 FROM dbo.ApplicantSyntheticWorkspace WHERE ApplicationId=application_row.ApplicationId)
    )
    SELECT
        CONCAT(N''EHF-2026-'',RIGHT(N''000''+CONVERT(nvarchar(10),ranked.ApplicationNumber),3)) AS ApplicationNumber,
        COALESCE(JSON_VALUE(identity_section.SnapshotJson,''$.fullName''),CONCAT(applicant.LegalGivenNames,N'' '',applicant.LegalFamilyName)) AS ApplicantName,
        TRY_CONVERT(decimal(8,2),JSON_VALUE(legacy_section.SnapshotJson,''$.age_observation'')) AS AgeObservation,
        COALESCE(TRY_CONVERT(decimal(8,2),DATEDIFF(day,academic_degree.PhdConferralDate,TRY_CONVERT(date,call_row.ApplicationDeadlineUtc))/365.2425),TRY_CONVERT(decimal(8,2),JSON_VALUE(legacy_section.SnapshotJson,''$.academic_age_observation''))) AS AcademicAgeObservation
    FROM ranked
    JOIN dbo.Application AS application_row ON application_row.ApplicationId=ranked.ApplicationId
    JOIN dbo.FellowshipCall AS call_row ON call_row.FellowshipCallId=application_row.FellowshipCallId
    JOIN dbo.Applicant AS applicant ON applicant.ApplicantId=application_row.ApplicantId
    OUTER APPLY (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion WHERE ApplicationId=application_row.ApplicationId AND SectionCode=''identity'' ORDER BY VersionNumber DESC) AS identity_section
    OUTER APPLY (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion WHERE ApplicationId=application_row.ApplicationId AND SectionCode=''qualifications'' ORDER BY VersionNumber DESC) AS qualification_section
    OUTER APPLY (SELECT COALESCE((SELECT MIN(TRY_CONVERT(date,JSON_VALUE(degree_row.value,''$.conferralDate''))) FROM OPENJSON(qualification_section.SnapshotJson,''$.degrees'') AS degree_row WHERE JSON_VALUE(degree_row.value,''$.degreeType'')=''PhD''),CASE WHEN JSON_VALUE(qualification_section.SnapshotJson,''$.degreeCategory'') IN (''PHD'',''MD_PHD'') THEN TRY_CONVERT(date,JSON_VALUE(qualification_section.SnapshotJson,''$.phdDate'')) END,(SELECT MIN(COALESCE(qualification.ConferralDate,qualification.PhdDate)) FROM dbo.Qualification AS qualification WHERE qualification.ApplicationId=application_row.ApplicationId AND qualification.DegreeType IN (''PHD'',''MD_PHD''))) AS PhdConferralDate) AS academic_degree
    OUTER APPLY (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion WHERE ApplicationId=application_row.ApplicationId AND SectionCode=''LEGACY_REGISTER_OBSERVATIONS'' ORDER BY VersionNumber DESC) AS legacy_section
    WHERE ranked.ApplicationId=@ApplicationId;

    SELECT publication_row.Title,publication_row.JournalText,publication_row.PublicationYear,
           publication_row.Doi,publication_row.HttpLink,
           JSON_VALUE(latest.EvidenceJson,''$.result_url'') AS OpenAlexUrl,
           latest.CitationCount,latest.EvidenceJson,publication_row.AuthorsText,
           JSON_VALUE(latest.EvidenceJson,''$.journal_openalex_id'') AS JournalOpenAlexId,
           JSON_VALUE(latest.EvidenceJson,''$.journal_openalex_name'') AS JournalOpenAlexName,
           TRY_CONVERT(decimal(18,6),JSON_VALUE(latest.EvidenceJson,''$.journal_two_year_mean_citedness'')) AS JournalTwoYearMeanCitedness,
           JSON_VALUE(latest.EvidenceJson,''$.journal_metric_observed_at_utc'') AS JournalMetricObservedAtUtc,
           latest_review.ReviewDisposition AS ReviewDisposition
    FROM dbo.ApplicationPublication AS publication_row
    OUTER APPLY (SELECT TOP (1) ReviewDisposition FROM dbo.ApplicationPublicationReview WHERE ApplicationPublicationId=publication_row.ApplicationPublicationId ORDER BY RecordedAtUtc DESC,ApplicationPublicationReviewId DESC) AS latest_review
    OUTER APPLY (SELECT TOP (1) CitationCount,CitationStatus,EvidenceJson FROM dbo.PublicationCitationObservation WHERE ApplicationPublicationId=publication_row.ApplicationPublicationId AND SourceCode=''OPENALEX'' ORDER BY CASE WHEN ObservedAtUtc IS NULL THEN 1 ELSE 0 END,ObservedAtUtc DESC,RecordedAtUtc DESC,PublicationCitationObservationId DESC) AS latest
    WHERE publication_row.ApplicationId=@ApplicationId
      AND latest_review.ReviewDisposition IN (''PUBLISHED'', ''ACCEPTED_PREPRINT'')
    ORDER BY publication_row.PublicationYear DESC,publication_row.Title,publication_row.ApplicationPublicationId;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.RecordPendingPublicationReview
    @ApplicationPublicationId uniqueidentifier,
    @ReviewDisposition varchar(32),
    @ReviewerIdentity nvarchar(255),
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @ActorGroup NOT IN(N''EHF-Administrators'',N''EHF-Trustees'')
        THROW 54704,''Internal authorization is required.'',1;
    IF @ReviewDisposition NOT IN(''PUBLISHED'',''ACCEPTED_PREPRINT'',''NON_PUBLICATION'')
        THROW 54705,''The review disposition is invalid.'',1;
    BEGIN TRY
        BEGIN TRANSACTION;
        DECLARE @Latest varchar(32), @EvidenceJson nvarchar(max);
        SELECT @Latest=r.ReviewDisposition
        FROM dbo.ApplicationPublication p WITH (UPDLOCK, HOLDLOCK)
        OUTER APPLY(SELECT TOP(1) ReviewDisposition FROM dbo.ApplicationPublicationReview WHERE ApplicationPublicationId=p.ApplicationPublicationId ORDER BY RecordedAtUtc DESC,ApplicationPublicationReviewId DESC) r
        WHERE p.ApplicationPublicationId=@ApplicationPublicationId;
        IF @Latest IS NULL OR @Latest <> ''PENDING_REVIEW''
            THROW 54706,''The publication is no longer pending review.'',1;
        SELECT @EvidenceJson=(SELECT N''internal-pending-paper-review'' AS source,@ActorGroup AS actorGroup,@ReviewDisposition AS action FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
        EXEC dbo.RecordApplicationPublicationReview
            @ApplicationPublicationId=@ApplicationPublicationId,
            @ReviewDisposition=@ReviewDisposition,
            @ReviewerIdentity=@ReviewerIdentity,
            @ReviewReason=N''Rapid internal pending-paper classification.'',
            @EvidenceJson=@EvidenceJson;
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

GRANT EXECUTE ON dbo.RecordApplicationPublicationReview TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetInternalApplicationMetrics TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetInternalApplicantMetricDetail TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.RecordPendingPublicationReview TO EHFApplicationRuntime;

PRINT 'PASS 047 decoupled publication disposition';
