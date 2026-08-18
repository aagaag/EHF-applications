SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @MetricsDefinition nvarchar(max) =
    OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P'));
IF @MetricsDefinition NOT LIKE '%PhdConferralDate%'
   OR @MetricsDefinition NOT LIKE '%OPENJSON(%$.degrees%'
   OR @MetricsDefinition NOT LIKE '%ApplicationDeadlineUtc%'
   OR @MetricsDefinition NOT LIKE '%$.phdDate%'
   OR @MetricsDefinition NOT LIKE '%MD_PHD%'
   OR @MetricsDefinition NOT LIKE '%ApplicantSyntheticWorkspace%'
   OR @MetricsDefinition NOT LIKE '%WHERE call_row.CallCode = N''EHF-2026''%'
   OR @MetricsDefinition NOT LIKE '%AND NOT EXISTS%'
    THROW 54000, 'Metrics must preserve academic age and exclude synthetic workspaces.', 1;

PRINT 'PASS 020 synthetic metrics academic age';
