SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.RecordApplicationPublicationReview',N'P') IS NULL
   OR OBJECT_ID(N'dbo.GetInternalApplicationMetrics',N'P') IS NULL
   OR OBJECT_ID(N'dbo.GetInternalApplicantMetricDetail',N'P') IS NULL
   OR OBJECT_ID(N'dbo.RecordPendingPublicationReview',N'P') IS NULL
    THROW 54720, 'The decoupled publication procedures are missing.', 1;

DECLARE @ReviewDefinition nvarchar(max)=OBJECT_DEFINITION(OBJECT_ID(N'dbo.RecordApplicationPublicationReview',N'P')),
        @MetricsDefinition nvarchar(max)=OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicationMetrics',N'P')),
        @DetailDefinition nvarchar(max)=OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicantMetricDetail',N'P')),
        @PendingDefinition nvarchar(max)=OBJECT_DEFINITION(OBJECT_ID(N'dbo.RecordPendingPublicationReview',N'P'));
IF @ReviewDefinition LIKE N'%Only a resolved record can be included in published-paper statistics%'
    THROW 54721, 'Published review decisions are still coupled to DOI resolution.', 1;
IF @DetailDefinition LIKE N'%publication_row.ResolutionStatus=''RESOLVED''%'
    THROW 54722, 'Applicant publication detail still excludes DOI-less reviewed papers.', 1;
IF @PendingDefinition LIKE N'%UPDATE dbo.ApplicationPublication SET ResolutionStatus%'
    THROW 54723, 'Pending-paper classification still fabricates DOI resolution.', 1;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallId uniqueidentifier=
                (SELECT FellowshipCallId FROM dbo.FellowshipCall WHERE CallCode=N'EHF-2026'),
            @ApplicantId uniqueidentifier='47000000-0000-4000-8000-000000000002',
            @ApplicationId uniqueidentifier='47000000-0000-4000-8000-000000000003',
            @RunId uniqueidentifier='47000000-0000-4000-8000-000000000004',
            @PublishedId uniqueidentifier='47000000-0000-4000-8000-000000000005',
            @PendingId uniqueidentifier='47000000-0000-4000-8000-000000000006';
    IF @CallId IS NULL
        THROW 54724, 'The EHF-2026 validation call is missing.', 1;
    INSERT dbo.Applicant (ApplicantId,FellowshipCallId,LegalGivenNames,LegalFamilyName)
    VALUES (@ApplicantId,@CallId,N'Synthetic',N'Disposition Validator');
    INSERT dbo.Application (ApplicationId,FellowshipCallId,ApplicantId,ApplicationStatus)
    VALUES (@ApplicationId,@CallId,@ApplicantId,'IMPORTED');
    INSERT dbo.ImportRun
        (ImportRunId,FellowshipCallId,ImportFingerprintSha256,ImporterVersion,RunStatus,
         StartedByIdentity,CompletedAtUtc)
    VALUES (@RunId,@CallId,HASHBYTES('SHA2_256',N'047 disposition'),
            '2026.10-disposition-validation','COMPLETED',N'validator',SYSUTCDATETIME());
    INSERT dbo.ApplicationPublication
        (ApplicationPublicationId,ApplicationId,CreatedByImportRunId,PublicationIdentitySha256,
         ManifestWorkKey,AuthorsText,Title,JournalText,PagesText,PublicationYear,ResolutionStatus)
    VALUES
        (@PublishedId,@ApplicationId,@RunId,HASHBYTES('SHA2_256',N'047 published'),
         'validator-047-published',N'Ada Author; Ben Biologist',N'DOI-less published paper',
         N'Journal of Validation',N'47-55',2026,'UNRESOLVED'),
        (@PendingId,@ApplicationId,@RunId,HASHBYTES('SHA2_256',N'047 pending'),
         'validator-047-pending',N'Ada Author; Ben Biologist',N'DOI-less pending paper',
         N'Journal of Validation',N'56-64',2026,'UNRESOLVED');

    EXEC dbo.RecordApplicationPublicationReview
        @ApplicationPublicationId=@PublishedId,
        @ReviewDisposition='PUBLISHED',
        @ReviewerIdentity=N'validator',
        @ReviewReason=N'Complete bibliographic evidence establishes publication.',
        @EvidenceJson=N'{"source":"validator-047","doi":null}';
    EXEC dbo.RecordApplicationPublicationReview
        @ApplicationPublicationId=@PendingId,
        @ReviewDisposition='PENDING_REVIEW',
        @ReviewerIdentity=N'validator',
        @ReviewReason=N'Awaiting rapid manual classification.',
        @EvidenceJson=N'{"source":"validator-047","doi":null}';
    EXEC dbo.RecordPendingPublicationReview
        @ApplicationPublicationId=@PendingId,
        @ReviewDisposition='PUBLISHED',
        @ReviewerIdentity=N'validator',
        @ActorGroup=N'EHF-Administrators';

    IF (SELECT COUNT(*) FROM dbo.ApplicationPublicationReview
        WHERE ApplicationPublicationId IN (@PublishedId,@PendingId)
          AND ReviewDisposition='PUBLISHED' AND ResolutionStatus='UNRESOLVED') <> 2
        THROW 54725, 'A DOI-less paper could not retain an audited PUBLISHED disposition.', 1;
    IF EXISTS
    (
        SELECT 1 FROM dbo.ApplicationPublication
        WHERE ApplicationPublicationId IN (@PublishedId,@PendingId)
          AND (ResolutionStatus<>'UNRESOLVED' OR Doi IS NOT NULL)
    )
        THROW 54726, 'Publication classification incorrectly changed DOI resolution state.', 1;

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
    IF NOT EXISTS
    (
        SELECT 1 FROM @Metrics
        WHERE ApplicationId=CONVERT(varchar(36),@ApplicationId)
          AND ValidatedPublishedPaperCount=2 AND ValidatedPreprintPaperCount=0
    )
        THROW 54727, 'DOI-less published paper was omitted from the aggregate metrics.', 1;
    IF @DetailDefinition NOT LIKE N'%ReviewDisposition IN (''PUBLISHED'', ''ACCEPTED_PREPRINT'')%'
       OR @DetailDefinition LIKE N'%publication_row.ResolutionStatus=''RESOLVED''%'
        THROW 54728, 'DOI-less published paper was omitted from applicant detail.', 1;

    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 047 decoupled publication disposition';
