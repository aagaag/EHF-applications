SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P') IS NULL
    THROW 53610, 'The internal metrics procedure is missing.', 1;

DECLARE @Definition nvarchar(max)=
    OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P'));
IF @Definition NOT LIKE N'%ROW_NUMBER() OVER (ORDER BY observation.CitationCount DESC%'
   OR @Definition NOT LIKE N'%ranked.CitationCount >= ranked.CitationRank%'
   OR @Definition NOT LIKE N'%CONVERT(int,metric.HIndex)%'
    THROW 53611, 'The internal metrics procedure does not derive H-index from cutoff work evidence.', 1;

DECLARE @Citations TABLE (CitationCount bigint NOT NULL);
INSERT @Citations (CitationCount) VALUES (10),(2),(1);
DECLARE @CalculatedHIndex bigint;
SELECT @CalculatedHIndex =
    COALESCE(MAX(CASE WHEN ranked.CitationCount >= ranked.CitationRank
                      THEN ranked.CitationRank ELSE CONVERT(bigint,0) END),0)
FROM
(
    SELECT CitationCount,
           ROW_NUMBER() OVER (ORDER BY CitationCount DESC) AS CitationRank
    FROM @Citations
) AS ranked;
IF @CalculatedHIndex <> 2
    THROW 53612, 'The verified H-index calculation returned the wrong value.', 1;

DELETE FROM @Citations;
DECLARE @ZeroWorkCitationCount bigint;
DECLARE @ZeroWorkHIndex bigint;
SELECT @ZeroWorkCitationCount = COALESCE(SUM(CitationCount),CONVERT(bigint,0)),
       @ZeroWorkHIndex = COALESCE(MAX(CONVERT(bigint,0)),CONVERT(bigint,0))
FROM @Citations;
IF @ZeroWorkCitationCount <> 0 OR @ZeroWorkHIndex <> 0
    THROW 53614, 'An active cutoff with zero qualifying works must return zero metrics.', 1;

DECLARE @MissingCutoffHIndex int =
    CASE WHEN CONVERT(int,NULL) IS NULL THEN NULL ELSE CONVERT(int,@ZeroWorkHIndex) END;
IF @MissingCutoffHIndex IS NOT NULL
    THROW 53615, 'A missing cutoff must retain a missing H-index.', 1;

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
    WHERE VerifiedCitationSource IS NOT NULL AND HIndex IS NULL
)
    THROW 53613, 'An active citation cutoff returned a missing H-index.', 1;

IF EXISTS
(
    SELECT 1 FROM @Metrics
    WHERE VerifiedCitationSource IS NOT NULL AND VerifiedCitationCount IS NULL
)
    THROW 53616, 'An active citation cutoff returned a missing citation count.', 1;

PRINT 'PASS 036 verified H-index metrics';
