SET NOCOUNT ON;
SET XACT_ABORT OFF;

IF OBJECT_ID(N'dbo.GetInternalApplicantMetricDetail', N'P') IS NULL
    THROW 53410, 'Applicant metric detail procedure is missing.', 1;

DECLARE @Definition nvarchar(max)=OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicantMetricDetail', N'P'));
IF @Definition NOT LIKE N'%JournalOpenAlexId%'
   OR @Definition NOT LIKE N'%JournalOpenAlexName%'
   OR @Definition NOT LIKE N'%JournalTwoYearMeanCitedness%'
   OR @Definition NOT LIKE N'%JournalMetricObservedAtUtc%'
   OR @Definition NOT LIKE N'%TRY_CONVERT(decimal(18,6)%'
    THROW 53411, 'Applicant journal metric projection is incomplete or unsafe.', 1;

IF EXISTS
(
    SELECT 1
    FROM sys.database_permissions AS permission_row
    WHERE permission_row.grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND permission_row.major_id = OBJECT_ID(N'dbo.GetInternalApplicantMetricDetail', N'P')
      AND permission_row.permission_name = N'EXECUTE'
      AND permission_row.state_desc NOT IN (N'GRANT', N'GRANT_WITH_GRANT_OPTION')
)
    THROW 53412, 'The runtime execute grant for applicant journal metrics is missing.', 1;

PRINT 'PASS 034 applicant journal metrics';
