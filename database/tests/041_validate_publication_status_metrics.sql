SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P') IS NULL
    THROW 54110, 'The internal metrics procedure is missing.', 1;
IF OBJECT_ID(N'dbo.GetInternalApplicantMetricDetail', N'P') IS NULL
    THROW 54111, 'The internal metric detail procedure is missing.', 1;

DECLARE @MetricsDefinition nvarchar(max)=OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P'));
IF @MetricsDefinition NOT LIKE N'%ValidatedPreprintPaperCount%'
   OR @MetricsDefinition NOT LIKE N'%COUNT_BIG(CASE WHEN latest_review.ReviewDisposition=''PUBLISHED'' THEN 1 END)%'
   OR @MetricsDefinition NOT LIKE N'%COUNT_BIG(CASE WHEN latest_review.ReviewDisposition=''ACCEPTED_PREPRINT'' THEN 1 END)%'
    THROW 54112, 'The internal metrics procedure does not separately count published papers and preprints.', 1;

DECLARE @DetailDefinition nvarchar(max)=OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicantMetricDetail', N'P'));
IF @DetailDefinition NOT LIKE N'%ReviewDisposition AS ReviewDisposition%'
   OR @DetailDefinition NOT LIKE N'%ReviewDisposition IN (''PUBLISHED'', ''ACCEPTED_PREPRINT'')%'
    THROW 54113, 'The internal metric detail procedure does not expose accepted preprints.', 1;

DECLARE @Metrics TABLE
(
    ApplicantName nvarchar(400), Degree nvarchar(max), AgeObservation decimal(8,2),
    AcademicAgeObservation decimal(8,2), SelfReportedGender nvarchar(100),
    FirstAuthorPaperCount int, LastAuthorPaperCount int, TotalPaperCount int,
    HIndex int, TotalCitations bigint, Orcid nvarchar(255),
    GoogleScholarCitationCount bigint, IdentityCertainty nvarchar(100),
    VerifiedCitationCount bigint, VerifiedCitationSource varchar(40),
    VerifiedCitationProfileUrl nvarchar(2048), ValidatedPublishedPaperCount bigint,
    ValidatedPreprintPaperCount bigint, ApplicationId varchar(36), ApplicationNumber nvarchar(4000)
);
INSERT @Metrics EXEC dbo.GetInternalApplicationMetrics @ActorGroup=N'EHF-Administrators';
IF EXISTS
(
    SELECT 1 FROM @Metrics
    WHERE ValidatedPublishedPaperCount IS NULL OR ValidatedPreprintPaperCount IS NULL
)
    THROW 54114, 'A valid application returned a missing publication-status total.', 1;

PRINT 'PASS 041 publication status metrics';
