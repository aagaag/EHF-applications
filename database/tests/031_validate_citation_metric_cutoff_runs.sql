SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.CitationMetricCutoffRun', N'U') IS NULL
    THROW 53120, 'Citation metric cutoff runs are missing.', 1;
IF OBJECT_ID(N'dbo.ActivateCitationMetricCutoffRun', N'P') IS NULL
    THROW 53121, 'Citation metric cutoff activation is missing.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.ActivateCitationMetricCutoffRun', N'P')) NOT LIKE N'%mixed sources%'
    THROW 53122, 'Citation cutoff activation does not reject mixed sources.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.ActivateCitationMetricCutoffRun', N'P')) NOT LIKE N'%citation cutoff is incomplete%'
    THROW 53123, 'Citation cutoff activation does not reject incomplete evidence.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P')) NOT LIKE N'%CitationMetricCutoffRun%'
    THROW 53124, 'Internal metrics do not use the active citation cutoff.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P')) LIKE N'%GOOGLE_SCHOLAR%'
    THROW 53125, 'Internal metrics must not fall back to Google Scholar.', 1;

PRINT 'PASS 031 citation metric cutoff runs';
