SET NOCOUNT ON;
SET XACT_ABORT ON;

EXEC(N'
CREATE VIEW dbo.vw_ApplicantFacingApplication
AS
    SELECT
        application_row.ApplicationId,
        CONCAT(applicant_row.LegalGivenNames, N'' '', applicant_row.LegalFamilyName) AS FullName,
        applicant_row.PreferredName,
        applicant_row.BirthMonth,
        applicant_row.BirthYear,
        applicant_row.SelfReportedGender,
        registered_email.ContactValue AS RegisteredEmail,
        alternative_email.ContactValue AS AlternativeEmail,
        telephone.ContactValue AS Telephone,
        employment.InstitutionName,
        employment.DepartmentName,
        employment.PositionTitle,
        employment.ClinicalWorkPercent,
        qualification.DegreeType,
        qualification.PhdDate,
        bibliometrics.FirstAuthorPaperCount,
        bibliometrics.LastAuthorPaperCount,
        bibliometrics.TotalPaperCount,
        bibliometrics.GoogleScholarCitationCount AS ApplicantReportedCitationTotal,
        contribution.StatementText AS ContributionStatement,
        application_row.ApplicationStatus,
        application_row.RowVersion AS ApplicationRowVersion
    FROM dbo.Application AS application_row
    JOIN dbo.Applicant AS applicant_row
      ON applicant_row.ApplicantId = application_row.ApplicantId
    OUTER APPLY
    (
        SELECT TOP (1) ContactValue
        FROM dbo.ApplicantContact
        WHERE ApplicantId = applicant_row.ApplicantId
          AND ContactType = ''REGISTERED_EMAIL''
          AND IsPrimary = 1
        ORDER BY ApplicantContactId
    ) AS registered_email
    OUTER APPLY
    (
        SELECT TOP (1) ContactValue
        FROM dbo.ApplicantContact
        WHERE ApplicantId = applicant_row.ApplicantId
          AND ContactType = ''ALTERNATIVE_EMAIL''
        ORDER BY IsPrimary DESC, ApplicantContactId
    ) AS alternative_email
    OUTER APPLY
    (
        SELECT TOP (1) ContactValue
        FROM dbo.ApplicantContact
        WHERE ApplicantId = applicant_row.ApplicantId
          AND ContactType = ''TELEPHONE''
        ORDER BY IsPrimary DESC, ApplicantContactId
    ) AS telephone
    OUTER APPLY
    (
        SELECT TOP (1) InstitutionName, DepartmentName, PositionTitle, ClinicalWorkPercent
        FROM dbo.EmploymentAffiliation
        WHERE ApplicationId = application_row.ApplicationId
        ORDER BY EmploymentAffiliationId
    ) AS employment
    OUTER APPLY
    (
        SELECT TOP (1) DegreeType, PhdDate
        FROM dbo.Qualification
        WHERE ApplicationId = application_row.ApplicationId
        ORDER BY QualificationId
    ) AS qualification
    LEFT JOIN dbo.Bibliometrics AS bibliometrics
      ON bibliometrics.ApplicationId = application_row.ApplicationId
    LEFT JOIN dbo.ContributionStatement AS contribution
      ON contribution.ApplicationId = application_row.ApplicationId;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantFacingApplication
    @SessionTokenSha256 binary(32)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @ScopedApplication uniqueidentifier;
    SELECT @ScopedApplication = session_row.ApplicationId
    FROM dbo.ApplicantSession AS session_row
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME();

    IF @ScopedApplication IS NULL
        RETURN;

    SELECT
        FullName, PreferredName, BirthMonth, BirthYear, SelfReportedGender,
        RegisteredEmail, AlternativeEmail, Telephone, InstitutionName,
        DepartmentName, PositionTitle, ClinicalWorkPercent, DegreeType, PhdDate,
        FirstAuthorPaperCount, LastAuthorPaperCount, TotalPaperCount,
        ApplicantReportedCitationTotal, ContributionStatement, ApplicationStatus,
        ApplicationRowVersion
    FROM dbo.vw_ApplicantFacingApplication
    WHERE ApplicationId = @ScopedApplication;

    SELECT
        DocumentId, DocumentVersionId, SlotCode, ByteSize, MediaType, PageCount
    FROM dbo.vw_ApplicantVisibleDocumentVersion
    WHERE ApplicationId = @ScopedApplication
    ORDER BY SlotCode, DocumentId;
END;
');

GRANT EXECUTE ON dbo.GetApplicantFacingApplication TO EHFApplicationRuntime;
DENY SELECT ON dbo.vw_ApplicantFacingApplication TO EHFApplicationRuntime;
