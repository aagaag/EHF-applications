SET NOCOUNT ON;
SET XACT_ABORT OFF;

IF OBJECT_ID(N'dbo.ListInternalApplicantDocuments', N'P') IS NULL
   OR OBJECT_ID(N'dbo.GetInternalApplicantDocument', N'P') IS NULL
    THROW 53510, 'The internal document procedures are missing.', 1;

DECLARE @ListDefinition nvarchar(max)=
            OBJECT_DEFINITION(OBJECT_ID(N'dbo.ListInternalApplicantDocuments', N'P')),
        @ReadDefinition nvarchar(max)=
            OBJECT_DEFINITION(OBJECT_ID(N'dbo.GetInternalApplicantDocument', N'P'));
IF @ListDefinition NOT LIKE N'%slot_row.CreatedByIdentity = N''ISAB01_IMPORT''%'
   OR @ListDefinition NOT LIKE N'%latest_decision.Classification = ''CONFIDENTIAL_RECOMMENDATION''%'
   OR @ReadDefinition NOT LIKE N'%slot_row.CreatedByIdentity = N''ISAB01_IMPORT''%'
   OR @ReadDefinition NOT LIKE N'%latest_decision.Classification = ''CONFIDENTIAL_RECOMMENDATION''%'
    THROW 53511, 'The internal import-package allowlist is incomplete.', 1;

IF NOT EXISTS
(
    SELECT 1 FROM sys.database_permissions AS permission_row
    WHERE permission_row.grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND permission_row.major_id = OBJECT_ID(N'dbo.ListInternalApplicantDocuments', N'P')
      AND permission_row.permission_name = N'EXECUTE'
      AND permission_row.state_desc IN (N'GRANT', N'GRANT_WITH_GRANT_OPTION')
)
OR NOT EXISTS
(
    SELECT 1 FROM sys.database_permissions AS permission_row
    WHERE permission_row.grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND permission_row.major_id = OBJECT_ID(N'dbo.GetInternalApplicantDocument', N'P')
      AND permission_row.permission_name = N'EXECUTE'
      AND permission_row.state_desc IN (N'GRANT', N'GRANT_WITH_GRANT_OPTION')
)
    THROW 53512, 'The runtime execute grants for internal packages are missing.', 1;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallId uniqueidentifier=NEWID(), @ApplicantId uniqueidentifier=NEWID(),
            @ApplicationId uniqueidentifier=NEWID(), @SlotId uniqueidentifier=NEWID(),
            @DocumentId uniqueidentifier=NEWID(), @ObjectId uniqueidentifier=NEWID(),
            @VersionId uniqueidentifier=NEWID(), @RunId uniqueidentifier=NEWID(),
            @OccurrenceId uniqueidentifier=NEWID();

    INSERT dbo.FellowshipCall
        (FellowshipCallId,CallCode,DisplayName,CallStatus,ApplicationDeadlineUtc)
    VALUES (@CallId,N'EHF-035-VALIDATION',N'Imported package validation','DRAFT','2027-01-31');
    INSERT dbo.Applicant (ApplicantId,FellowshipCallId,LegalGivenNames,LegalFamilyName)
    VALUES (@ApplicantId,@CallId,N'Synthetic',N'Imported Package');
    INSERT dbo.Application (ApplicationId,FellowshipCallId,ApplicantId,ApplicationStatus)
    VALUES (@ApplicationId,@CallId,@ApplicantId,'IMPORTED');
    INSERT dbo.DocumentSlot
        (DocumentSlotId,ApplicationId,SlotCode,SlotLabel,ApplicantVisible,CreatedByIdentity)
    VALUES (@SlotId,@ApplicationId,'APPLICATION',N'Application',0,N'ISAB01_IMPORT');
    INSERT dbo.Document (DocumentId,DocumentSlotId,DocumentType,CreatedByIdentity)
    VALUES (@DocumentId,@SlotId,'OTHER',N'ISAB01_IMPORT');
    INSERT dbo.StoredObject
        (StoredObjectId,ObjectKey,KeyVersion,EnvelopeVersion,AesGcmNonce,
         PlaintextSha256,CiphertextSha256,ByteSize,MediaType,PageCount,
         ScanEngine,ScannedAtUtc,ScanResult,CreatedByIdentity)
    VALUES
        (@ObjectId,'567890abcdef1234567890abcdef1234',1,1,
         CONVERT(binary(12),0x030405060708090A0B0C0D0E),
         HASHBYTES('SHA2_256',N'035 plain'),HASHBYTES('SHA2_256',N'035 cipher'),125,
         'application/pdf',1,'validator',SYSUTCDATETIME(),'CLEAN',N'ISAB01_IMPORT');
    INSERT dbo.DocumentVersion
        (DocumentVersionId,DocumentId,StoredObjectId,VersionNumber,Classification,CreatedByIdentity)
    VALUES (@VersionId,@DocumentId,@ObjectId,1,'UNREVIEWED',N'ISAB01_IMPORT');
    UPDATE dbo.DocumentSlot SET ActiveDocumentVersionId=@VersionId WHERE DocumentSlotId=@SlotId;
    INSERT dbo.ImportRun
        (ImportRunId,FellowshipCallId,ImportFingerprintSha256,ImporterVersion,RunStatus,
         StartedByIdentity,CompletedAtUtc)
    VALUES (@RunId,@CallId,HASHBYTES('SHA2_256',N'035 run'),'035-validator','COMPLETED',
            N'validator',SYSUTCDATETIME());
    INSERT dbo.SourceOccurrence
        (SourceOccurrenceId,ImportRunId,ApplicationId,DocumentVersionId,
         SourceLocatorSha256,SourceContentSha256,SourceByteSize,ImportDisposition)
    VALUES (@OccurrenceId,@RunId,@ApplicationId,@VersionId,
            HASHBYTES('SHA2_256',N'035 locator'),HASHBYTES('SHA2_256',N'035 content'),
            125,'INGESTED');

    DECLARE @Listed TABLE
    (
        DocumentSlotId uniqueidentifier, DocumentVersionId uniqueidentifier,
        SlotCode varchar(80), SlotLabel nvarchar(200), VersionNumber int,
        DocumentStatus varchar(12)
    );
    INSERT @Listed EXEC dbo.ListInternalApplicantDocuments
        @ApplicationId=@ApplicationId,@ActorIdentity=N'cloudflare:trustee',
        @ActorGroup=N'EHF-Trustees';
    IF NOT EXISTS (SELECT 1 FROM @Listed WHERE DocumentVersionId=@VersionId)
        THROW 53513, 'The imported application document was not listed.', 1;

    DECLARE @Opened TABLE
    (
        ApplicationId uniqueidentifier, DocumentId uniqueidentifier,
        DocumentVersionId uniqueidentifier, StoredObjectId uniqueidentifier,
        ObjectKey varchar(32), KeyVersion smallint, EnvelopeVersion tinyint,
        AesGcmNonce binary(12), PlaintextSha256 binary(32),
        CiphertextSha256 binary(32), ByteSize bigint
    );
    INSERT @Opened EXEC dbo.GetInternalApplicantDocument
        @ApplicationId=@ApplicationId,@DocumentVersionId=@VersionId,
        @ActorIdentity=N'cloudflare:trustee',@ActorGroup=N'EHF-Trustees',
        @AccessPurpose='PACKAGE';
    IF NOT EXISTS (SELECT 1 FROM @Opened WHERE DocumentVersionId=@VersionId)
        THROW 53514, 'The imported application document could not be opened.', 1;

    INSERT dbo.ClassificationDecision
        (SourceOccurrenceId,Classification,Reason,DecidedByIdentity)
    VALUES (@OccurrenceId,'CONFIDENTIAL_RECOMMENDATION',
            N'Confidential fixture for package validation.',N'validator');

    DELETE FROM @Listed;
    INSERT @Listed EXEC dbo.ListInternalApplicantDocuments
        @ApplicationId=@ApplicationId,@ActorIdentity=N'cloudflare:trustee',
        @ActorGroup=N'EHF-Trustees';
    IF EXISTS (SELECT 1 FROM @Listed WHERE DocumentVersionId=@VersionId)
        THROW 53515, 'A confidential imported document was listed.', 1;

    DELETE FROM @Opened;
    INSERT @Opened EXEC dbo.GetInternalApplicantDocument
        @ApplicationId=@ApplicationId,@DocumentVersionId=@VersionId,
        @ActorIdentity=N'cloudflare:trustee',@ActorGroup=N'EHF-Trustees',
        @AccessPurpose='PACKAGE';
    IF EXISTS (SELECT 1 FROM @Opened WHERE DocumentVersionId=@VersionId)
        THROW 53516, 'A confidential imported document could be opened.', 1;

    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 035 internal import package';
