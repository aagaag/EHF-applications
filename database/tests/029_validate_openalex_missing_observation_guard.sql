IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P')) NOT LIKE N'%COUNT(CASE WHEN latest.CitationStatus=''OBSERVED'' THEN 1 END)=0%'
    THROW 52920, 'Internal metrics do not distinguish absent OpenAlex observations from zero citations.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P')) NOT LIKE N'%THEN NULL%'
    THROW 52921, 'Internal metrics return a fabricated citation total when OpenAlex observations are absent.', 1;

PRINT 'PASS 029 OpenAlex missing-observation guard';
