SET NOCOUNT ON;
SET XACT_ABORT ON;

IF NOT EXISTS (SELECT 1 FROM dbo.FellowshipCall WHERE CallCode = N'EHF-2026')
BEGIN
    INSERT dbo.FellowshipCall
        (CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc, PublicSlug,
         CompactTitle, ApplicantReviewStatus, InternalSelectionStatus,
         InvitationsEnabled, AnalysisProfileCode)
    VALUES
        (N'EHF-2026', N'SQL permission test call', 'DRAFT', DATEADD(day, 1, SYSUTCDATETIME()),
         'ehf-2026', N'SQL permission test call', 'OPEN', 'OPEN', 0, 'ehf-standard-v1');
END;

DECLARE @CallId uniqueidentifier =
    (SELECT FellowshipCallId FROM dbo.FellowshipCall WHERE CallCode = N'EHF-2026');

IF NOT EXISTS (
    SELECT 1 FROM dbo.FellowshipCallGroupGrant
    WHERE FellowshipCallId = @CallId AND GroupName = N'EHF-Administrators'
      AND AccessRole = 'ADMINISTER'
)
    INSERT dbo.FellowshipCallGroupGrant (FellowshipCallId, GroupName, AccessRole)
    VALUES (@CallId, N'EHF-Administrators', 'ADMINISTER');

IF NOT EXISTS (
    SELECT 1 FROM dbo.FellowshipCallGroupGrant
    WHERE FellowshipCallId = @CallId AND GroupName = N'EHF-Trustees'
      AND AccessRole = 'READ'
)
    INSERT dbo.FellowshipCallGroupGrant (FellowshipCallId, GroupName, AccessRole)
    VALUES (@CallId, N'EHF-Trustees', 'READ');
