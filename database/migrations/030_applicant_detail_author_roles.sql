SET NOCOUNT ON;
SET XACT_ABORT ON;

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
           latest.CitationCount,latest.EvidenceJson,publication_row.AuthorsText
    FROM dbo.ApplicationPublication AS publication_row
    OUTER APPLY (SELECT TOP (1) ReviewDisposition FROM dbo.ApplicationPublicationReview WHERE ApplicationPublicationId=publication_row.ApplicationPublicationId ORDER BY RecordedAtUtc DESC,ApplicationPublicationReviewId DESC) AS latest_review
    OUTER APPLY (SELECT TOP (1) CitationCount,CitationStatus,EvidenceJson FROM dbo.PublicationCitationObservation WHERE ApplicationPublicationId=publication_row.ApplicationPublicationId AND SourceCode=''OPENALEX'' ORDER BY CASE WHEN ObservedAtUtc IS NULL THEN 1 ELSE 0 END,ObservedAtUtc DESC,RecordedAtUtc DESC,PublicationCitationObservationId DESC) AS latest
    WHERE publication_row.ApplicationId=@ApplicationId
      AND publication_row.ResolutionStatus=''RESOLVED''
      AND latest_review.ReviewDisposition=''PUBLISHED''
    ORDER BY publication_row.PublicationYear DESC,publication_row.Title,publication_row.ApplicationPublicationId;
END;
');

GRANT EXECUTE ON dbo.GetInternalApplicantMetricDetail TO EHFApplicationRuntime;
