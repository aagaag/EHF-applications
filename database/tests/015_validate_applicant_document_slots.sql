SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.TR_ApplicantReopenScope_OpenDocumentSlot', N'TR') IS NULL
    THROW 52490, 'The document-slot reopen trigger is missing.', 1;

IF COL_LENGTH(N'dbo.DocumentSlot', N'ApplicantUploadMode') IS NULL
    THROW 52411, 'Applicant document slot state is missing.', 1;
IF OBJECT_ID(N'dbo.ApplicantDocumentSubmission', N'U') IS NULL
    THROW 52412, 'Applicant document submission history is missing.', 1;
IF OBJECT_ID(N'dbo.ValidateApplicantUploadSlot', N'P') IS NULL
    THROW 52413, 'The session-scoped upload-slot validator is missing.', 1;
IF OBJECT_ID(N'dbo.GetApplicantDocumentSlots', N'P') IS NULL
    THROW 52414, 'The applicant document checklist procedure is missing.', 1;
IF OBJECT_ID(N'dbo.ValidateApplicantFinalDocuments', N'P') IS NULL
    THROW 52415, 'The applicant final-document validator is missing.', 1;

PRINT 'PASS 015 applicant document slots';
