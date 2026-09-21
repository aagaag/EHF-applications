SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.ListApplicantPreviewDocuments', N'P') IS NULL
    THROW 52930, 'ListApplicantPreviewDocuments is missing.', 1;
IF OBJECT_ID(N'dbo.GetApplicantPreviewDocument', N'P') IS NULL
    THROW 52931, 'GetApplicantPreviewDocument is missing.', 1;
IF OBJECT_DEFINITION(OBJECT_ID(N'dbo.ListApplicantPreviews', N'P'))
       NOT LIKE N'%AcademicAgeYears%'
    THROW 52932, 'The applicant review card metrics are missing from the preview listing.', 1;

BEGIN TRY
    EXEC dbo.ListApplicantPreviewDocuments
        @ApplicationId='25000000-0000-4000-8000-000000000099',
        @ActorIdentity=N'cloudflare:validator',
        @ActorGroup=N'EHF-Trustees';
    THROW 52933, 'A trustee applicant document listing was not rejected.', 1;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() <> 52920 THROW;
END CATCH;
BEGIN TRY
    EXEC dbo.ListApplicantPreviewDocuments
        @ApplicationId='25000000-0000-4000-8000-000000000099',
        @ActorIdentity=N'   ',
        @ActorGroup=N'EHF-Administrators';
    THROW 52934, 'A document listing without an actor identity was not rejected.', 1;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() <> 52920 THROW;
END CATCH;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallId uniqueidentifier = '25000000-0000-4000-8000-000000000001';
    DECLARE @ApplicantId uniqueidentifier = '25000000-0000-4000-8000-000000000002';
    DECLARE @ApplicationId uniqueidentifier = '25000000-0000-4000-8000-000000000003';
    DECLARE @ImportRunId uniqueidentifier = '25000000-0000-4000-8000-000000000004';
    DECLARE @SlotId uniqueidentifier = '25000000-0000-4000-8000-000000000005';
    DECLARE @DocumentId uniqueidentifier = '25000000-0000-4000-8000-000000000006';
    DECLARE @VersionId uniqueidentifier = '25000000-0000-4000-8000-000000000007';
    DECLARE @StoredObjectId uniqueidentifier = '25000000-0000-4000-8000-000000000008';

    INSERT dbo.FellowshipCall
        (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
    VALUES
        (@CallId, N'EHF-025-VALIDATION', N'Applicant review documents validation',
         'CLOSED', '2027-06-30');
    INSERT dbo.Applicant (ApplicantId, LegalGivenNames, LegalFamilyName)
    VALUES (@ApplicantId, N'Synthetic', N'ReviewDocuments');
    INSERT dbo.Application
        (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus)
    VALUES (@ApplicationId, @CallId, @ApplicantId, 'IMPORTED');
    INSERT dbo.ApplicantPortalBaseline
        (ApplicationId, ProjectionJson, CreatedByIdentity)
    VALUES
        (@ApplicationId,
         N'{"applicant":{"fullName":"Synthetic Review Documents",'
         N'"researchArea":"Synthetic neurodegeneration","hIndex":9,'
         N'"applicantReportedCitationTotal":500}}',
         N'validator');
    INSERT dbo.ApplicationSectionVersion
        (ApplicationId, SectionCode, VersionNumber, SnapshotJson, ChangedByIdentity)
    VALUES
        (@ApplicationId, 'LEGACY_REGISTER_OBSERVATIONS', 1,
         N'{"academic_age_observation":3.5,"h_index":4,"total_citations":321}',
         N'validator');
    INSERT dbo.ImportRun
        (ImportRunId, FellowshipCallId, ImportFingerprintSha256, ImporterVersion,
         RunStatus, StartedByIdentity, CompletedAtUtc)
    VALUES
        (@ImportRunId, @CallId, CONVERT(binary(32), REPLICATE('A1', 32), 2),
         'validator-1', 'COMPLETED', N'validator', SYSUTCDATETIME());
    INSERT dbo.ApplicantCitationProfileObservation
        (ApplicationId, ImportRunId, SourceCode, ProfileUrl, CitationCount, HIndex,
         WorksCount, EvidenceJson, ObservedAtUtc)
    VALUES
        (@ApplicationId, @ImportRunId, 'OPENALEX', N'https://openalex.org/A2500000000',
         512, 10, 40, N'{"matchMethod":"validator"}', SYSUTCDATETIME());
    INSERT dbo.DocumentSlot
        (DocumentSlotId, ApplicationId, SlotCode, SlotLabel, CreatedByIdentity,
         ApplicantUploadMode, ApplicantVisible, RequiredForCompletion)
    VALUES
        (@SlotId, @ApplicationId, 'import-2500000000ff', N'Research plan', N'validator',
         'CLOSED', 0, 0);
    INSERT dbo.StoredObject
        (StoredObjectId, ObjectKey, KeyVersion, EnvelopeVersion, AesGcmNonce,
         PlaintextSha256, CiphertextSha256, ByteSize, MediaType, PageCount,
         ScanEngine, ScanResult, ScannedAtUtc, CreatedByIdentity)
    VALUES
        (@StoredObjectId, '250000000000000000000000000000ff', 1, 1,
         0x000000000000000000000000,
         0x0000000000000000000000000000000000000000000000000000000000000001,
         0x0000000000000000000000000000000000000000000000000000000000000002,
         1024, 'application/pdf', 3, 'validator', 'CLEAN', SYSUTCDATETIME(), N'validator');
    INSERT dbo.Document (DocumentId, DocumentSlotId, DocumentType, CreatedByIdentity)
    VALUES (@DocumentId, @SlotId, 'RESEARCH_PLAN', N'validator');
    INSERT dbo.DocumentVersion
        (DocumentVersionId, DocumentId, StoredObjectId, VersionNumber, Classification,
         CreatedByIdentity)
    VALUES (@VersionId, @DocumentId, @StoredObjectId, 1, 'UNREVIEWED', N'validator');
    UPDATE dbo.DocumentSlot
    SET ActiveDocumentVersionId = @VersionId
    WHERE DocumentSlotId = @SlotId;

    DECLARE @Cards TABLE
    (
        ApplicationId uniqueidentifier,
        ApplicantName nvarchar(401),
        ApplicationStatus varchar(20),
        AcademicAgeYears decimal(8,2),
        HIndex int,
        CitationCount bigint,
        CitationSource varchar(40),
        CitationProfileUrl nvarchar(1000),
        ResearchArea nvarchar(400),
        DocumentCount bigint
    );
    INSERT @Cards EXEC dbo.ListApplicantPreviews @ActorGroup=N'EHF-Administrators';
    IF NOT EXISTS
       (SELECT 1 FROM @Cards
        WHERE ApplicationId = @ApplicationId
          AND ApplicantName = N'Synthetic Review Documents'
          AND ApplicationStatus = 'IMPORTED'
          AND AcademicAgeYears = 3.50
          AND HIndex = 9
          AND CitationCount = 512
          AND CitationSource = 'OPENALEX'
          AND CitationProfileUrl = N'https://openalex.org/A2500000000'
          AND ResearchArea = N'Synthetic neurodegeneration'
          AND DocumentCount = 1)
        THROW 52935, 'The applicant review card metrics were not derived from the approved sources.', 1;

    DECLARE @DocumentsHeader TABLE
    (
        ApplicationId uniqueidentifier,
        ApplicantName nvarchar(401),
        ApplicationStatus varchar(20)
    );
    DECLARE @Documents TABLE
    (
        DocumentVersionId uniqueidentifier,
        SlotCode varchar(80),
        SlotLabel nvarchar(200),
        DocumentType varchar(40),
        Classification varchar(40),
        PageCount int,
        ByteSize bigint,
        MediaType varchar(100),
        ScanResult varchar(20),
        ScanSignature nvarchar(200),
        CreatedAtUtc datetime2(7)
    );
    INSERT @DocumentsHeader
    EXEC dbo.ListApplicantPreviewDocuments
        @ApplicationId=@ApplicationId,
        @ActorIdentity=N'cloudflare:validator',
        @ActorGroup=N'EHF-Administrators';
    INSERT @Documents
    EXEC dbo.ListApplicantPreviewDocuments
        @ApplicationId=@ApplicationId,
        @ActorIdentity=N'cloudflare:validator',
        @ActorGroup=N'EHF-Administrators';
    IF (SELECT COUNT_BIG(*) FROM @DocumentsHeader) <> 1
       OR NOT EXISTS
          (SELECT 1 FROM @DocumentsHeader
           WHERE ApplicationId = @ApplicationId
             AND ApplicantName = N'Synthetic Review Documents')
        THROW 52936, 'The exact requested applicant document header was not returned.', 1;
    IF (SELECT COUNT_BIG(*) FROM @Documents) <> 1
       OR NOT EXISTS
          (SELECT 1 FROM @Documents
           WHERE DocumentVersionId = @VersionId
             AND DocumentType = 'RESEARCH_PLAN'
             AND Classification = 'UNREVIEWED'
             AND PageCount = 3)
        THROW 52937, 'The applicant document listing did not return the active proposal PDF.', 1;
    IF NOT EXISTS
       (SELECT 1 FROM dbo.AuditEvent
        WHERE ApplicationId = @ApplicationId
          AND EventType = 'APPLICANT_PREVIEW_DOCUMENTS_OPENED'
          AND ActorIdentity = N'cloudflare:validator'
          AND EntityId = @ApplicationId)
        THROW 52938, 'Listing applicant proposal documents was not audited.', 1;

    BEGIN TRY
        EXEC dbo.ListApplicantPreviewDocuments
            @ApplicationId='25000000-0000-4000-8000-000000000098',
            @ActorIdentity=N'cloudflare:validator',
            @ActorGroup=N'EHF-Administrators';
        THROW 52939, 'An unknown application document listing was not rejected.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() <> 52921 THROW;
    END CATCH;

    BEGIN TRY
        EXEC dbo.GetApplicantPreviewDocument
            @DocumentVersionId='25000000-0000-4000-8000-000000000098',
            @ActorIdentity=N'cloudflare:validator',
            @ActorGroup=N'EHF-Administrators';
        THROW 52940, 'An unknown applicant document was not rejected.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() <> 52921 THROW;
    END CATCH;

    DECLARE @File TABLE
    (
        ApplicationId uniqueidentifier,
        DocumentId uniqueidentifier,
        DocumentVersionId uniqueidentifier,
        StoredObjectId uniqueidentifier,
        ObjectKey varchar(32),
        KeyVersion smallint,
        EnvelopeVersion tinyint,
        AesGcmNonce binary(12),
        PlaintextSha256 binary(32),
        CiphertextSha256 binary(32),
        ByteSize bigint,
        MediaType varchar(100),
        PageCount int,
        SlotCode varchar(80),
        DocumentType varchar(40)
    );
    INSERT @File
    EXEC dbo.GetApplicantPreviewDocument
        @DocumentVersionId=@VersionId,
        @ActorIdentity=N'cloudflare:validator',
        @ActorGroup=N'EHF-Administrators';
    IF NOT EXISTS
       (SELECT 1 FROM @File
        WHERE ApplicationId = @ApplicationId
          AND DocumentVersionId = @VersionId
          AND ObjectKey = '250000000000000000000000000000ff'
          AND PageCount = 3
          AND MediaType = 'application/pdf')
        THROW 52941, 'The applicant proposal PDF envelope was not returned.', 1;
    IF NOT EXISTS
       (SELECT 1 FROM dbo.AuditEvent
        WHERE ApplicationId = @ApplicationId
          AND EventType = 'APPLICANT_PREVIEW_DOCUMENT_OPENED'
          AND ActorIdentity = N'cloudflare:validator'
          AND EntityId = @VersionId)
        THROW 52942, 'Opening an applicant proposal PDF was not audited.', 1;

    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 025 applicant review documents';
