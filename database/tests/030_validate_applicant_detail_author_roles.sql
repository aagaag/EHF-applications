IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicantMetricDetail', N'P')) NOT LIKE N'%publication_row.AuthorsText%'
    THROW 53001, 'Applicant metric detail does not expose publication authors for lead-author highlighting.', 1;

PRINT 'PASS 030 applicant detail author roles';
