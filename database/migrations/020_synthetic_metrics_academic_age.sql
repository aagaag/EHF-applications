SET NOCOUNT ON;
SET XACT_ABORT ON;

EXEC(N'
ALTER PROCEDURE dbo.GetInternalApplicationMetrics
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    IF @ActorGroup NOT IN
       (N''EHF-Administrators'', N''EHF-Trustees'')
        THROW 51725, ''The internal metrics role is not authorized.'', 1;
    SELECT
        COALESCE(JSON_VALUE(identity_section.SnapshotJson, ''$.fullName''),
                 CONCAT(applicant.LegalGivenNames, N'' '', applicant.LegalFamilyName))
            AS ApplicantName,
        COALESCE(
            (SELECT STRING_AGG(JSON_VALUE(degree_row.value, ''$.degreeType''), N'', '')
             WITHIN GROUP (ORDER BY TRY_CONVERT(int, degree_row.[key]))
             FROM OPENJSON(qualification_section.SnapshotJson, ''$.degrees'') AS degree_row),
            JSON_VALUE(qualification_section.SnapshotJson, ''$.degreeCategory''),
            JSON_VALUE(legacy_section.SnapshotJson, ''$.degree'')) AS Degree,
        TRY_CONVERT(decimal(8,2), JSON_VALUE(legacy_section.SnapshotJson, ''$.age_observation''))
            AS AgeObservation,
        COALESCE(
            TRY_CONVERT(
                decimal(8,2),
                DATEDIFF(
                    day,
                    academic_degree.PhdConferralDate,
                    TRY_CONVERT(date, call_row.ApplicationDeadlineUtc)
                ) / 365.2425
            ),
            TRY_CONVERT(decimal(8,2), JSON_VALUE(
                legacy_section.SnapshotJson, ''$.academic_age_observation''))
        ) AS AcademicAgeObservation,
        COALESCE(JSON_VALUE(identity_section.SnapshotJson, ''$.gender''),
                 applicant.SelfReportedGender) AS SelfReportedGender,
        COALESCE(TRY_CONVERT(int, JSON_VALUE(publication_section.SnapshotJson, ''$.firstAuthorPaperCount'')),
                 bibliometrics.FirstAuthorPaperCount) AS FirstAuthorPaperCount,
        COALESCE(TRY_CONVERT(int, JSON_VALUE(publication_section.SnapshotJson, ''$.lastAuthorPaperCount'')),
                 bibliometrics.LastAuthorPaperCount) AS LastAuthorPaperCount,
        COALESCE(TRY_CONVERT(int, JSON_VALUE(publication_section.SnapshotJson, ''$.totalPaperCount'')),
                 bibliometrics.TotalPaperCount) AS TotalPaperCount,
        COALESCE(TRY_CONVERT(int, JSON_VALUE(publication_section.SnapshotJson, ''$.hIndex'')),
                 TRY_CONVERT(int, JSON_VALUE(legacy_section.SnapshotJson, ''$.h_index''))) AS HIndex,
        COALESCE(TRY_CONVERT(bigint, JSON_VALUE(publication_section.SnapshotJson, ''$.applicantReportedCitationTotal'')),
                 TRY_CONVERT(bigint, JSON_VALUE(legacy_section.SnapshotJson, ''$.total_citations''))) AS TotalCitations,
        COALESCE(JSON_VALUE(publication_section.SnapshotJson, ''$.orcid''),
                 JSON_VALUE(legacy_section.SnapshotJson, ''$.orcid'')) AS Orcid,
        bibliometrics.GoogleScholarCitationCount AS GoogleScholarCitationCount,
        JSON_VALUE(legacy_section.SnapshotJson, ''$.identity_certainty'') AS IdentityCertainty
    FROM dbo.Application AS application_row
    JOIN dbo.FellowshipCall AS call_row
      ON call_row.FellowshipCallId = application_row.FellowshipCallId
    JOIN dbo.Applicant AS applicant
      ON applicant.ApplicantId = application_row.ApplicantId
    LEFT JOIN dbo.Bibliometrics AS bibliometrics
      ON bibliometrics.ApplicationId = application_row.ApplicationId
    OUTER APPLY
    (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion
     WHERE ApplicationId = application_row.ApplicationId AND SectionCode = ''identity''
     ORDER BY VersionNumber DESC) AS identity_section
    OUTER APPLY
    (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion
     WHERE ApplicationId = application_row.ApplicationId AND SectionCode = ''qualifications''
     ORDER BY VersionNumber DESC) AS qualification_section
    OUTER APPLY
    (
        SELECT COALESCE(
            (SELECT MIN(TRY_CONVERT(date, JSON_VALUE(
                        degree_row.value, ''$.conferralDate'')))
             FROM OPENJSON(
                    qualification_section.SnapshotJson, ''$.degrees'') AS degree_row
             WHERE JSON_VALUE(
                       degree_row.value, ''$.degreeType'') = ''PhD''),
            CASE
              WHEN JSON_VALUE(qualification_section.SnapshotJson,
                              ''$.degreeCategory'') IN (''PHD'', ''MD_PHD'')
                THEN TRY_CONVERT(date, JSON_VALUE(
                     qualification_section.SnapshotJson, ''$.phdDate''))
            END,
            (SELECT MIN(COALESCE(qualification.ConferralDate,
                                 qualification.PhdDate))
             FROM dbo.Qualification AS qualification
             WHERE qualification.ApplicationId = application_row.ApplicationId
               AND qualification.DegreeType IN (''PHD'', ''MD_PHD''))
        ) AS PhdConferralDate
    ) AS academic_degree
    OUTER APPLY
    (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion
     WHERE ApplicationId = application_row.ApplicationId AND SectionCode = ''publications''
     ORDER BY VersionNumber DESC) AS publication_section
    OUTER APPLY
    (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion
     WHERE ApplicationId = application_row.ApplicationId
       AND SectionCode = ''LEGACY_REGISTER_OBSERVATIONS''
     ORDER BY VersionNumber DESC) AS legacy_section
    WHERE call_row.CallCode = N''EHF-2026''
      AND NOT EXISTS
      (
          SELECT 1 FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
          WHERE workspace_row.ApplicationId = application_row.ApplicationId
      )
    ORDER BY applicant.LegalFamilyName, applicant.LegalGivenNames;
END;
');
