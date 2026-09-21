SET NOCOUNT ON;
SET XACT_ABORT ON;

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
        CASE WHEN cutoff.CitationMetricCutoffRunId IS NULL THEN NULL ELSE CONVERT(int,metric.HIndex) END AS HIndex,
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
    OUTER APPLY
    (
        SELECT COALESCE(SUM(ranked.CitationCount),CONVERT(bigint,0)) AS CitationCount,
               COUNT_BIG(*) AS PublishedPaperCount,
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
    ) AS metric
    WHERE call_row.CallCode=N''EHF-2026''
      AND NOT EXISTS (SELECT 1 FROM dbo.ApplicantSyntheticWorkspace WHERE ApplicationId=application_row.ApplicationId)
    ORDER BY applicant.LegalFamilyName,applicant.LegalGivenNames,application_row.ApplicationId;
END;
');

GRANT EXECUTE ON dbo.GetInternalApplicationMetrics TO EHFApplicationRuntime;

PRINT 'PASS 036 verified H-index metrics';
