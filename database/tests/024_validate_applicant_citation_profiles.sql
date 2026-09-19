SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.ApplicantCitationProfileObservation', N'U') IS NULL
    THROW 52400, 'Applicant citation profile observation table is missing.', 1;
IF NOT EXISTS
(
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.ApplicantCitationProfileObservation')
      AND name = N'IX_ApplicantCitationProfileObservation_Latest'
)
    THROW 52401, 'Applicant citation profile latest index is missing.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P'))
       NOT LIKE N'%VerifiedCitationCount%'
    THROW 52402, 'Verified citation profile observation is missing from the metrics projection.', 1;

PRINT 'PASS 024 applicant citation profiles';
