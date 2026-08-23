SET NOCOUNT ON;
SET XACT_ABORT ON;

IF NOT EXISTS
(
    SELECT 1
    FROM sys.check_constraints
    WHERE parent_object_id=OBJECT_ID(N'dbo.PublicationCitationObservation')
      AND name=N'CK_PublicationCitationObservation_Source'
      AND is_disabled=0 AND is_not_trusted=0
      AND definition LIKE N'%OPENALEX%'
      AND definition LIKE N'%SEMANTIC_SCHOLAR%'
)
    THROW 54070, 'The open citation source constraint is missing or untrusted.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetApplicantPreview')) NOT LIKE N'%OpenAlexCitationCount%'
   OR OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetApplicantPreview')) NOT LIKE N'%SemanticScholarCitationCount%'
    THROW 54071, 'The applicant preview does not expose both open citation sources.', 1;
IF NOT EXISTS
(
    SELECT 1 FROM sys.database_permissions
    WHERE grantee_principal_id=DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND major_id=OBJECT_ID(N'dbo.GetApplicantPreview')
      AND permission_name=N'EXECUTE' AND state IN (N'G',N'W')
)
    THROW 54073, 'The runtime preview execution grant is missing.', 1;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallId uniqueidentifier='23000000-0000-4000-8000-000000000001',
            @ApplicantId uniqueidentifier='23000000-0000-4000-8000-000000000002',
            @ApplicationId uniqueidentifier='23000000-0000-4000-8000-000000000003',
            @RunId uniqueidentifier='23000000-0000-4000-8000-000000000004',
            @PublicationId uniqueidentifier='23000000-0000-4000-8000-000000000005';
    INSERT dbo.FellowshipCall
        (FellowshipCallId,CallCode,DisplayName,CallStatus,ApplicationDeadlineUtc)
    VALUES (@CallId,N'EHF-023-VALIDATION',N'Open citation validation','DRAFT','2027-01-31');
    INSERT dbo.Applicant (ApplicantId,LegalGivenNames,LegalFamilyName)
    VALUES (@ApplicantId,N'Synthetic',N'Citation');
    INSERT dbo.Application
        (ApplicationId,FellowshipCallId,ApplicantId,ApplicationStatus)
    VALUES (@ApplicationId,@CallId,@ApplicantId,'IMPORTED');
    INSERT dbo.ApplicantPortalBaseline
        (ApplicationId,ProjectionJson,CreatedByIdentity)
    VALUES
        (@ApplicationId,N'{"applicant":{"fullName":"Synthetic Citation"}}',N'validator');
    INSERT dbo.ImportRun
        (ImportRunId,FellowshipCallId,ImportFingerprintSha256,ImporterVersion,RunStatus,
         StartedByIdentity,CompletedAtUtc)
    VALUES
        (@RunId,@CallId,HASHBYTES('SHA2_256',N'023 open citations'),
         '2026.4-open-citations','COMPLETED',N'validator',SYSUTCDATETIME());
    INSERT dbo.ApplicationPublication
        (ApplicationPublicationId,ApplicationId,CreatedByImportRunId,
         PublicationIdentitySha256,ManifestWorkKey,Doi,AuthorsText,Title,
         JournalText,VolumeText,PagesText,PublicationYear,ResolutionStatus)
    VALUES
        (@PublicationId,@ApplicationId,@RunId,HASHBYTES('SHA2_256',N'023 publication'),
         'validator-open-citation','10.1000/open-citation',N'Ada Author',
         N'Open Citation Preview Publication',N'Journal of Validation','13','201-209',
         2026,'RESOLVED');
    INSERT dbo.PublicationCitationObservation
        (ApplicationPublicationId,ImportRunId,SourceCode,CitationCount,CitationStatus,
         EvidenceJson,ObservedAtUtc,PayloadSha256,RecordedAtUtc)
    VALUES
        (@PublicationId,@RunId,'OPENALEX',19,'OBSERVED',N'{"source":"OpenAlex"}',
         '2026-01-01',HASHBYTES('SHA2_256',N'023 openalex older'),'2026-08-02'),
        (@PublicationId,@RunId,'OPENALEX',29,'OBSERVED',N'{"source":"OpenAlex"}',
         '2026-08-01',HASHBYTES('SHA2_256',N'023 openalex newer'),'2026-08-01'),
        (@PublicationId,@RunId,'SEMANTIC_SCHOLAR',23,'OBSERVED',
         N'{"source":"Semantic Scholar"}','2026-08-01',
         HASHBYTES('SHA2_256',N'023 semantic scholar'),'2026-08-01');

    DECLARE @PublicationRows TABLE
    (
        ApplicationPublicationId uniqueidentifier,
        AuthorsText nvarchar(max),
        Title nvarchar(2000),
        JournalText nvarchar(1000),
        VolumeText nvarchar(255),
        PagesText nvarchar(255),
        PublicationYear smallint,
        CitationCount bigint,
        CitationStatus varchar(40),
        Doi varchar(255),
        OpenAlexCitationCount bigint,
        OpenAlexCitationStatus varchar(40),
        SemanticScholarCitationCount bigint,
        SemanticScholarCitationStatus varchar(40)
    );
    INSERT @PublicationRows
    EXEC dbo.GetApplicantPreview
        @ApplicationId=@ApplicationId,
        @ActorIdentity=N'cloudflare:validator',
        @ActorGroup=N'EHF-Administrators',
        @EmitResult=0,
        @EmitDrafts=0,
        @EmitPublications=1;
    IF NOT EXISTS
    (
        SELECT 1 FROM @PublicationRows
        WHERE ApplicationPublicationId=@PublicationId
          AND OpenAlexCitationCount=29
          AND OpenAlexCitationStatus='OBSERVED'
          AND SemanticScholarCitationCount=23
          AND SemanticScholarCitationStatus='OBSERVED'
    )
        THROW 54072, 'The preview did not return the latest count from both sources.', 1;

    EXECUTE AS USER=N'ehf_app';
    EXEC dbo.GetApplicantPreview
        @ApplicationId=@ApplicationId,
        @ActorIdentity=N'cloudflare:runtime-validator',
        @ActorGroup=N'EHF-Administrators',
        @EmitResult=0,
        @EmitDrafts=0,
        @EmitPublications=0;
    REVERT;

    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF USER_NAME()=N'ehf_app' REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 023 open citation sources';
