SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.ApplicantSectionConfirmation', N'U') IS NULL
    THROW 52231, 'The section confirmation table is missing.', 1;
IF OBJECT_ID(N'dbo.ApplicantFinalConfirmation', N'U') IS NULL
    THROW 52232, 'The final confirmation table is missing.', 1;
IF OBJECT_ID(N'dbo.ApplicantReopenScope', N'U') IS NULL
    THROW 52233, 'The reopen scope table is missing.', 1;
IF OBJECT_ID(N'dbo.ReopenApplicantScope', N'P') IS NULL
    THROW 52234, 'The bounded reopen procedure is missing.', 1;
IF OBJECT_ID(N'dbo.ConfirmApplicantSection', N'P') IS NULL
    THROW 52236, 'The section confirmation procedure is missing.', 1;
IF OBJECT_ID(N'dbo.SubmitApplicantFinalConfirmation', N'P') IS NULL
    THROW 52237, 'The atomic final-submission procedure is missing.', 1;
IF HAS_PERMS_BY_NAME(N'dbo.ConfirmApplicantSection', N'OBJECT', N'EXECUTE') <> 1
    THROW 52238, 'The runtime cannot execute section confirmation.', 1;
IF HAS_PERMS_BY_NAME(N'dbo.SubmitApplicantFinalConfirmation', N'OBJECT', N'EXECUTE') <> 1
    THROW 52239, 'The runtime cannot execute final submission.', 1;
IF NOT EXISTS
(
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.ApplicantFinalConfirmation')
      AND name = N'UX_ApplicantFinalConfirmation_Active'
      AND is_unique = 1
      AND has_filter = 1
)
    THROW 52235, 'Active final confirmations are not unique.', 1;

PRINT 'PASS 013 applicant confirmations';
