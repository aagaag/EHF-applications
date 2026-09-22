SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.DF_FellowshipCall_PublicSlug', N'D') IS NULL
   OR OBJECT_ID(N'dbo.DF_FellowshipCall_AnalysisProfileCode', N'D') IS NULL
    THROW 54530, 'The multi-call compatibility defaults are missing.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM sys.foreign_keys
    WHERE name = N'FK_Application_CallApplicant'
      AND update_referential_action_desc = N'CASCADE'
)
    THROW 54531, 'Applicant call ownership does not cascade to its application.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.CreateSyntheticApplicantWorkspace', N'P'))
       NOT LIKE N'%ApplicantId, FellowshipCallId%'
    THROW 54532, 'Synthetic workspaces do not create call-owned applicants.', 1;

PRINT 'PASS 042 multi-call compatibility';
