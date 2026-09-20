SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @MetricsDefinition nvarchar(max) =
    OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P'));
DECLARE @NormalizedMetricsDefinition nvarchar(max) =
    REPLACE(@MetricsDefinition, N' ', N'');
IF @NormalizedMetricsDefinition NOT LIKE '%PhdConferralDate%'
   OR @NormalizedMetricsDefinition NOT LIKE '%OPENJSON(%$.degrees%'
   OR @NormalizedMetricsDefinition NOT LIKE '%ApplicationDeadlineUtc%'
   OR @NormalizedMetricsDefinition NOT LIKE '%$.phdDate%'
   OR @NormalizedMetricsDefinition NOT LIKE '%MD_PHD%'
   OR @NormalizedMetricsDefinition NOT LIKE '%ApplicantSyntheticWorkspace%'
   OR @NormalizedMetricsDefinition NOT LIKE '%WHEREcall_row.CallCode=N''EHF-2026''%'
   OR @NormalizedMetricsDefinition NOT LIKE '%ANDNOTEXISTS%'
    THROW 54000, 'Metrics must preserve academic age and exclude synthetic workspaces.', 1;

PRINT 'PASS 020 synthetic metrics academic age';
