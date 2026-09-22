SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.FellowshipCallGroupGrant', N'U') IS NULL
    THROW 54540, 'Fellowship call grants are missing.', 1;
IF COL_LENGTH(N'dbo.FellowshipCall', N'PublicSlug') IS NULL
   OR COL_LENGTH(N'dbo.Applicant', N'FellowshipCallId') IS NULL
    THROW 54541, 'Call ownership columns are missing.', 1;
IF OBJECT_ID(N'dbo.ListAuthorizedFellowshipCalls', N'P') IS NULL
   OR OBJECT_ID(N'dbo.GetAuthorizedFellowshipCallBySlug', N'P') IS NULL
   OR OBJECT_ID(N'dbo.GetPublicFellowshipCallBySlug', N'P') IS NULL
    THROW 54542, 'Call lookup procedures are missing.', 1;
IF NOT EXISTS
(
    SELECT 1 FROM dbo.FellowshipCall
    WHERE CallCode=N'EHF-2026' AND PublicSlug='ehf-2026'
      AND AnalysisProfileCode='ehf-standard-v1' AND InvitationsEnabled=0
)
    THROW 54543, 'The legacy EHF-2026 call was not safely backfilled.', 1;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @AdminRows TABLE (FellowshipCallId uniqueidentifier, CallCode nvarchar(50), PublicSlug varchar(80), DisplayName nvarchar(200), CompactTitle nvarchar(120), CallStatus varchar(20), ApplicantReviewStatus varchar(20), InternalSelectionStatus varchar(20), InvitationsEnabled bit, AnalysisProfileCode varchar(40), ApplicationDeadlineUtc datetime2(7), ApplicantReviewDeadlineUtc datetime2(7), RowVersion binary(8));
    INSERT @AdminRows EXEC dbo.GetAuthorizedFellowshipCallBySlug @PublicSlug='ehf-2026', @ActorGroup=N'EHF-Administrators', @RequiredRole='READ';
    IF NOT EXISTS (SELECT 1 FROM @AdminRows WHERE PublicSlug='ehf-2026')
        THROW 54544, 'Administrators cannot resolve the legacy call.', 1;
    IF EXISTS (SELECT 1 FROM @AdminRows WHERE InvitationsEnabled<>0)
        THROW 54545, 'Legacy invitations must remain disabled.', 1;
    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 040 multi-call foundation';
