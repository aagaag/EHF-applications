IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P')) NOT LIKE N'%OPENALEX_WORK_CUTOFF%'
    THROW 52910, 'Internal metrics do not use the OpenAlex work-level cutoff.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P')) LIKE N'%ApplicantCitationProfileObservation%'
    THROW 52911, 'Internal metrics still use mixed applicant profile sources.', 1;
IF OBJECT_ID(N'dbo.GetInternalApplicantMetricDetail', N'P') IS NULL
    THROW 52912, 'The applicant metric detail procedure is missing.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicantMetricDetail', N'P')) NOT LIKE N'%EvidenceJson%'
    THROW 52913, 'The applicant metric detail omits annual OpenAlex evidence.', 1;
