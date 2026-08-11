SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.ApplicantSectionDraft', N'U') IS NULL
    THROW 52221, 'The applicant section draft table is missing.', 1;
IF OBJECT_ID(N'dbo.ApplicantFieldCorrection', N'U') IS NULL
    THROW 52222, 'The applicant correction history is missing.', 1;
IF OBJECT_ID(N'dbo.SaveApplicantSectionDraft', N'P') IS NULL
    THROW 52223, 'The applicant draft procedure is missing.', 1;
IF OBJECT_ID(N'dbo.TR_ApplicantFieldCorrection_AppendOnly', N'TR') IS NULL
    THROW 52224, 'Applicant correction history is not protected.', 1;

PRINT 'PASS 012 applicant drafts';
