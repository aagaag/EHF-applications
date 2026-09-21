SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.ApplicationPublicationReview', N'U') IS NULL
    THROW 54090, 'The publication review table is missing.', 1;
IF OBJECT_ID(N'dbo.TR_ApplicationPublicationReview_AppendOnly', N'TR') IS NULL
    THROW 54091, 'The publication review append-only trigger is missing.', 1;
IF OBJECT_ID(N'dbo.RecordApplicationPublicationReview', N'P') IS NULL
   OR OBJECT_ID(N'dbo.PromoteApplicationPublication', N'P') IS NULL
    THROW 54092, 'The publication review procedures are missing.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetApplicantPreview', N'P')) NOT LIKE N'%ReviewDisposition%'
   OR OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetApplicantPreview', N'P')) NOT LIKE N'%EvidenceJson%'
    THROW 54093, 'The applicant preview does not expose publication review evidence.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P'))
       NOT LIKE N'%ValidatedPublishedPaperCount%'
    THROW 54094, 'The independently validated publication count is missing.', 1;
IF EXISTS
(
    SELECT 1
    FROM sys.database_permissions
    WHERE grantee_principal_id=DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND major_id=OBJECT_ID(N'dbo.ApplicationPublicationReview')
      AND permission_name IN (N'SELECT',N'INSERT',N'UPDATE',N'DELETE')
      AND state IN (N'G',N'W')
)
    THROW 54095, 'The runtime role must not directly modify publication reviews.', 1;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallId uniqueidentifier='25000000-0000-4000-8000-000000000001',
            @ApplicantId uniqueidentifier='25000000-0000-4000-8000-000000000002',
            @ApplicationId uniqueidentifier='25000000-0000-4000-8000-000000000003',
            @RunId uniqueidentifier='25000000-0000-4000-8000-000000000004',
            @PublicationId uniqueidentifier='25000000-0000-4000-8000-000000000005';
    INSERT dbo.FellowshipCall
        (FellowshipCallId,CallCode,DisplayName,CallStatus,ApplicationDeadlineUtc)
    VALUES (@CallId,N'EHF-025-VALIDATION',N'Publication review validation','DRAFT','2027-01-31');
    INSERT dbo.Applicant (ApplicantId,LegalGivenNames,LegalFamilyName)
    VALUES (@ApplicantId,N'Synthetic',N'Reviewer');
    INSERT dbo.Application (ApplicationId,FellowshipCallId,ApplicantId,ApplicationStatus)
    VALUES (@ApplicationId,@CallId,@ApplicantId,'IMPORTED');
    INSERT dbo.ApplicantPortalBaseline (ApplicationId,ProjectionJson,CreatedByIdentity)
    VALUES (@ApplicationId,N'{"applicant":{"fullName":"Synthetic Reviewer"}}',N'validator');
    INSERT dbo.ImportRun
        (ImportRunId,FellowshipCallId,ImportFingerprintSha256,ImporterVersion,RunStatus,
         StartedByIdentity,CompletedAtUtc)
    VALUES (@RunId,@CallId,HASHBYTES('SHA2_256',N'025 review'),
            '2026.5-publication-review','COMPLETED',N'validator',SYSUTCDATETIME());
    INSERT dbo.ApplicationPublication
        (ApplicationPublicationId,ApplicationId,CreatedByImportRunId,PublicationIdentitySha256,
         ManifestWorkKey,ResolutionStatus)
    VALUES (@PublicationId,@ApplicationId,@RunId,HASHBYTES('SHA2_256',N'025 unresolved'),
            'validator-unresolved','UNRESOLVED');
    INSERT dbo.ApplicationPublicationSourceOccurrence
        (ApplicationPublicationId,ImportRunId,SourceType,SourceLocatorSha256,SourcePage,
         RawCitation,PayloadSha256)
    VALUES (@PublicationId,@RunId,'DOSSIER',HASHBYTES('SHA2_256',N'025 locator'),4,
            N'Candidate citation as reported by the applicant.',HASHBYTES('SHA2_256',N'025 source'));

    EXEC dbo.PromoteApplicationPublication
        @ApplicationPublicationId=@PublicationId,
        @Doi='10.1000/validator.review',
        @HttpLink=N'https://doi.org/10.1000/validator.review',
        @AuthorsText=N'Ada Author; Ben Biologist',
        @Title=N'Validated publication',
        @JournalText=N'Journal of Validation',
        @VolumeText=N'25', @PagesText=N'250-259', @PublicationYear=2026,
        @ReviewerIdentity=N'validator',
        @ReviewReason=N'Validated against the DOI landing page.',
        @EvidenceJson=N'{"doi":"10.1000/validator.review","source":"validator"}';

    IF NOT EXISTS
    (
        SELECT 1 FROM dbo.ApplicationPublication
        WHERE ApplicationPublicationId=@PublicationId
          AND ResolutionStatus='RESOLVED' AND Doi='10.1000/validator.review'
          AND Title=N'Validated publication' AND PublicationYear=2026
    )
        THROW 54096, 'The audited promotion did not fill canonical metadata and resolve the record.', 1;
    IF NOT EXISTS
    (
        SELECT 1 FROM dbo.ApplicationPublicationReview
        WHERE ApplicationPublicationId=@PublicationId AND ReviewDisposition='PUBLISHED'
          AND ResolutionStatus='RESOLVED' AND ReviewReason=N'Validated against the DOI landing page.'
    )
        THROW 54097, 'The promotion did not record a published review disposition.', 1;
    IF NOT EXISTS
    (
        SELECT 1 FROM dbo.AuditEvent
        WHERE ApplicationId=@ApplicationId AND EventType='PUBLICATION_REVIEW_RECORDED'
    )
        THROW 54098, 'The publication review audit event is missing.', 1;

    DECLARE @PublicationRows TABLE
    (
        ApplicationPublicationId uniqueidentifier, AuthorsText nvarchar(max), Title nvarchar(2000),
        JournalText nvarchar(1000), VolumeText nvarchar(255), PagesText nvarchar(255),
        PublicationYear smallint, CitationCount bigint, CitationStatus varchar(40), Doi varchar(255),
        OpenAlexCitationCount bigint, OpenAlexCitationStatus varchar(40),
        SemanticScholarCitationCount bigint, SemanticScholarCitationStatus varchar(40),
        ResolutionStatus varchar(20), ReviewDisposition varchar(32), ReviewReason nvarchar(2000),
        EvidenceJson nvarchar(max), RawCitation nvarchar(max), SourcePage int
    );
    INSERT @PublicationRows
    EXEC dbo.GetApplicantPreview @ApplicationId=@ApplicationId,
         @ActorIdentity=N'cloudflare:validator', @ActorGroup=N'EHF-Administrators',
         @EmitResult=0, @EmitDrafts=0, @EmitPublications=1;
    IF NOT EXISTS
    (
        SELECT 1 FROM @PublicationRows
        WHERE ApplicationPublicationId=@PublicationId AND ResolutionStatus='RESOLVED'
          AND ReviewDisposition='PUBLISHED' AND SourcePage=4
          AND RawCitation=N'Candidate citation as reported by the applicant.'
    )
        THROW 54099, 'The applicant preview does not return review status and source evidence.', 1;

    EXECUTE AS USER=N'ehf_app';
    EXEC dbo.GetApplicantPreview @ApplicationId=@ApplicationId,
         @ActorIdentity=N'cloudflare:runtime-validator', @ActorGroup=N'EHF-Administrators',
         @EmitResult=0, @EmitDrafts=0, @EmitPublications=1;
    REVERT;

    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF USER_NAME()=N'ehf_app' REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 025 publication review workflow';
