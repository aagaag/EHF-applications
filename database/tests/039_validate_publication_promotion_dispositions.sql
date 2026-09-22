SET NOCOUNT ON;

IF OBJECT_ID(N'dbo.PromoteApplicationPublication', N'P') IS NULL
    THROW 54447, 'The publication promotion procedure is missing.', 1;

DECLARE @Definition nvarchar(max) = OBJECT_DEFINITION(
    OBJECT_ID(N'dbo.PromoteApplicationPublication', N'P')
);
IF @Definition NOT LIKE '%@ReviewDisposition varchar(32)%'
    THROW 54448, 'The publication promotion procedure does not accept a review disposition.', 1;
IF @Definition NOT LIKE '%@ReviewDisposition=@ReviewDisposition%'
    THROW 54449, 'The publication promotion procedure does not record the requested disposition.', 1;
IF @Definition LIKE '%@ReviewDisposition=''PUBLISHED''%'
    THROW 54450, 'The publication promotion procedure still forces a PUBLISHED review.', 1;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallId uniqueidentifier='39000000-0000-4000-8000-000000000001',
            @ApplicantId uniqueidentifier='39000000-0000-4000-8000-000000000002',
            @ApplicationId uniqueidentifier='39000000-0000-4000-8000-000000000003',
            @RunId uniqueidentifier='39000000-0000-4000-8000-000000000004',
            @PublicationId uniqueidentifier='39000000-0000-4000-8000-000000000005';
    INSERT dbo.FellowshipCall
        (FellowshipCallId,CallCode,DisplayName,CallStatus,ApplicationDeadlineUtc)
    VALUES (@CallId,N'EHF-039-VALIDATION',N'Promotion disposition validation','DRAFT','2027-01-31');
    INSERT dbo.Applicant (ApplicantId,FellowshipCallId,LegalGivenNames,LegalFamilyName)
    VALUES (@ApplicantId,@CallId,N'Synthetic',N'Promoter');
    INSERT dbo.Application (ApplicationId,FellowshipCallId,ApplicantId,ApplicationStatus)
    VALUES (@ApplicationId,@CallId,@ApplicantId,'IMPORTED');
    INSERT dbo.ApplicantPortalBaseline (ApplicationId,ProjectionJson,CreatedByIdentity)
    VALUES (@ApplicationId,N'{"applicant":{"fullName":"Synthetic Promoter"}}',N'validator');
    INSERT dbo.ImportRun
        (ImportRunId,FellowshipCallId,ImportFingerprintSha256,ImporterVersion,RunStatus,
         StartedByIdentity,CompletedAtUtc)
    VALUES (@RunId,@CallId,HASHBYTES('SHA2_256',N'039 promotion disposition'),
            '2026.9-promotion-disposition','COMPLETED',N'validator',SYSUTCDATETIME());
    INSERT dbo.ApplicationPublication
        (ApplicationPublicationId,ApplicationId,CreatedByImportRunId,PublicationIdentitySha256,
         ManifestWorkKey,ResolutionStatus)
    VALUES (@PublicationId,@ApplicationId,@RunId,HASHBYTES('SHA2_256',N'039 unresolved'),
            'validator-039-unresolved','UNRESOLVED');

    EXEC dbo.PromoteApplicationPublication
        @ApplicationPublicationId=@PublicationId,
        @Doi='10.1000/validator.promotion-disposition',
        @HttpLink=N'https://doi.org/10.1000/validator.promotion-disposition',
        @AuthorsText=N'Ada Author; Ben Biologist',
        @Title=N'Accepted validation manuscript',
        @JournalText=N'Journal of Validation',
        @PublicationYear=2026,
        @ReviewDisposition='ACCEPTED_PREPRINT',
        @ReviewerIdentity=N'validator',
        @ReviewReason=N'Accepted manuscript disposition validation.',
        @EvidenceJson=N'{"source":"validator-039"}';

    IF (SELECT COUNT(*) FROM dbo.ApplicationPublicationReview
        WHERE ApplicationPublicationId=@PublicationId) <> 1
        THROW 54451, 'Promotion must record exactly one review decision.', 1;
    IF NOT EXISTS
    (
        SELECT 1
        FROM dbo.ApplicationPublicationReview
        WHERE ApplicationPublicationId=@PublicationId
          AND ReviewDisposition='ACCEPTED_PREPRINT'
          AND ResolutionStatus='RESOLVED'
          AND ReviewReason=N'Accepted manuscript disposition validation.'
    )
        THROW 54452, 'Promotion did not atomically record the requested disposition.', 1;

    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 039 publication promotion dispositions';
