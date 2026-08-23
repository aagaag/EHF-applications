SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.GetApplicantPreview', N'P') IS NULL
    THROW 54060, 'GetApplicantPreview is missing.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetApplicantPreview')) NOT LIKE N'%ApplicationPublication%'
    THROW 54061, 'GetApplicantPreview does not expose application publications.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM sys.database_permissions AS permission_row
    WHERE permission_row.grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND permission_row.major_id = OBJECT_ID(N'dbo.GetApplicantPreview')
      AND permission_row.permission_name = N'EXECUTE'
      AND permission_row.state IN (N'G', N'W')
)
    THROW 54062, 'The runtime preview execution grant is missing.', 1;

BEGIN TRY
    EXEC dbo.GetApplicantPreview
        @ApplicationId='22000000-0000-4000-8000-000000000099',
        @ActorIdentity=N'cloudflare:trustee',
        @ActorGroup=N'EHF-Trustees',
        @EmitResult=0,
        @EmitDrafts=0,
        @EmitPublications=0;
    THROW 54063, 'Trustee publication preview was not rejected.', 1;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() <> 52810 THROW;
END CATCH;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallId uniqueidentifier='22000000-0000-4000-8000-000000000001',
            @ApplicantId uniqueidentifier='22000000-0000-4000-8000-000000000002',
            @ApplicationId uniqueidentifier='22000000-0000-4000-8000-000000000003',
            @RunId uniqueidentifier='22000000-0000-4000-8000-000000000004',
            @PublicationId uniqueidentifier='22000000-0000-4000-8000-000000000005';
    INSERT dbo.FellowshipCall
        (FellowshipCallId,CallCode,DisplayName,CallStatus,ApplicationDeadlineUtc)
    VALUES
        (@CallId,N'EHF-022-VALIDATION',N'Publication preview validation','DRAFT','2027-01-31');
    INSERT dbo.Applicant (ApplicantId,LegalGivenNames,LegalFamilyName)
    VALUES (@ApplicantId,N'Synthetic',N'Preview');
    INSERT dbo.Application
        (ApplicationId,FellowshipCallId,ApplicantId,ApplicationStatus)
    VALUES (@ApplicationId,@CallId,@ApplicantId,'IMPORTED');
    INSERT dbo.ApplicantPortalBaseline
        (ApplicationId,ProjectionJson,CreatedByIdentity)
    VALUES
        (@ApplicationId,N'{"applicant":{"fullName":"Synthetic Preview"}}',N'validator');
    INSERT dbo.ImportRun
        (ImportRunId,FellowshipCallId,ImportFingerprintSha256,ImporterVersion,RunStatus,
         StartedByIdentity,CompletedAtUtc)
    VALUES
        (@RunId,@CallId,HASHBYTES('SHA2_256',N'022 publication preview'),
         '2026.4-publications','COMPLETED',N'validator',SYSUTCDATETIME());
    INSERT dbo.ApplicationPublication
        (ApplicationPublicationId,ApplicationId,CreatedByImportRunId,
         PublicationIdentitySha256,ManifestWorkKey,Doi,AuthorsText,Title,
         JournalText,VolumeText,PagesText,PublicationYear,ResolutionStatus)
    VALUES
        (@PublicationId,@ApplicationId,@RunId,HASHBYTES('SHA2_256',N'022 publication'),
         'validator-preview','10.1000/preview',N'Ada Author; Ben Biologist',
         N'Synthetic Preview Publication',N'Journal of Validation','12','101-109',
         2025,'RESOLVED');
    INSERT dbo.PublicationCitationObservation
        (ApplicationPublicationId,ImportRunId,SourceCode,CitationCount,CitationStatus,
         EvidenceJson,ObservedAtUtc,PayloadSha256,RecordedAtUtc)
    VALUES
        (@PublicationId,@RunId,'GOOGLE_SCHOLAR',37,'OBSERVED',N'{"source":"validator"}',
         '2026-01-01',HASHBYTES('SHA2_256',N'022 scholar older observation'),'2026-08-02'),
        (@PublicationId,@RunId,'GOOGLE_SCHOLAR',41,'OBSERVED',N'{"source":"validator"}',
         '2026-08-01',HASHBYTES('SHA2_256',N'022 scholar newer observation'),'2026-08-01');

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
    IF (SELECT COUNT_BIG(*) FROM @PublicationRows) <> 1
       OR NOT EXISTS
          (SELECT 1 FROM @PublicationRows
           WHERE ApplicationPublicationId=@PublicationId
             AND AuthorsText=N'Ada Author; Ben Biologist'
             AND Title=N'Synthetic Preview Publication'
             AND JournalText=N'Journal of Validation'
             AND VolumeText=N'12'
             AND PagesText=N'101-109'
             AND PublicationYear=2025
             AND CitationCount=41
             AND CitationStatus='OBSERVED'
             AND Doi='10.1000/preview')
        THROW 54064, 'The administrator publication preview row is invalid.', 1;

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

PRINT 'PASS 022 applicant publication preview';
