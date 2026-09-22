SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.ListInternalApplicantDocuments', N'P') IS NULL
   OR OBJECT_ID(N'dbo.GetInternalApplicantDocument', N'P') IS NULL
   OR OBJECT_ID(N'dbo.RecordInternalDocumentAccessOutcome', N'P') IS NULL
    THROW 54190, 'The internal document access procedures are missing.', 1;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallId uniqueidentifier=NEWID(), @ApplicantId uniqueidentifier=NEWID(),
            @ApplicationId uniqueidentifier=NEWID(), @SlotId uniqueidentifier=NEWID(),
            @DocumentId uniqueidentifier=NEWID(), @ObjectId uniqueidentifier=NEWID(),
            @VersionId uniqueidentifier=NEWID(), @RunId uniqueidentifier=NEWID(),
            @OccurrenceId uniqueidentifier=NEWID();
    INSERT dbo.FellowshipCall
        (FellowshipCallId,CallCode,DisplayName,CallStatus,ApplicationDeadlineUtc)
    VALUES (@CallId,N'EHF-026-VALIDATION',N'Internal document validation','DRAFT','2027-01-31');
    INSERT dbo.Applicant (ApplicantId,FellowshipCallId,LegalGivenNames,LegalFamilyName)
    VALUES (@ApplicantId,@CallId,N'Synthetic',N'Document Reviewer');
    INSERT dbo.Application (ApplicationId,FellowshipCallId,ApplicantId,ApplicationStatus)
    VALUES (@ApplicationId,@CallId,@ApplicantId,'IMPORTED');
    INSERT dbo.DocumentSlot
        (DocumentSlotId,ApplicationId,SlotCode,SlotLabel,ApplicantVisible,CreatedByIdentity)
    VALUES (@SlotId,@ApplicationId,'CV',N'Curriculum vitae',1,N'validator');
    INSERT dbo.Document (DocumentId,DocumentSlotId,DocumentType,CreatedByIdentity)
    VALUES (@DocumentId,@SlotId,'CV',N'validator');
    INSERT dbo.StoredObject
        (StoredObjectId,ObjectKey,KeyVersion,EnvelopeVersion,AesGcmNonce,
         PlaintextSha256,CiphertextSha256,ByteSize,MediaType,PageCount,
         ScanEngine,ScannedAtUtc,ScanResult,CreatedByIdentity)
    VALUES
        (@ObjectId,'34567890abcdef1234567890abcdef12',1,1,
         CONVERT(binary(12),0x0102030405060708090A0B0C),
         HASHBYTES('SHA2_256',N'026 plain'),HASHBYTES('SHA2_256',N'026 cipher'),123,
         'application/pdf',1,'validator',SYSUTCDATETIME(),'CLEAN',N'validator');
    INSERT dbo.DocumentVersion
        (DocumentVersionId,DocumentId,StoredObjectId,VersionNumber,Classification,CreatedByIdentity)
    VALUES (@VersionId,@DocumentId,@ObjectId,1,'APPLICANT_VISIBLE',N'validator');
    UPDATE dbo.DocumentSlot SET ActiveDocumentVersionId=@VersionId WHERE DocumentSlotId=@SlotId;
    INSERT dbo.ImportRun
        (ImportRunId,FellowshipCallId,ImportFingerprintSha256,ImporterVersion,RunStatus,
         StartedByIdentity,CompletedAtUtc)
    VALUES (@RunId,@CallId,HASHBYTES('SHA2_256',N'026 run'),'026-validator','COMPLETED',
            N'validator',SYSUTCDATETIME());
    INSERT dbo.SourceOccurrence
        (SourceOccurrenceId,ImportRunId,ApplicationId,DocumentVersionId,
         SourceLocatorSha256,SourceContentSha256,SourceByteSize,ImportDisposition)
    VALUES (@OccurrenceId,@RunId,@ApplicationId,@VersionId,
            HASHBYTES('SHA2_256',N'026 locator'),HASHBYTES('SHA2_256',N'026 content'),
            123,'INGESTED');
    INSERT dbo.ClassificationDecision
        (SourceOccurrenceId,Classification,Reason,DecidedByIdentity)
    VALUES (@OccurrenceId,'APPLICANT_VISIBLE',N'Validated applicant-visible fixture.',N'validator');

    DECLARE @Listed TABLE
    (
        DocumentSlotId uniqueidentifier, DocumentVersionId uniqueidentifier,
        SlotCode varchar(80), SlotLabel nvarchar(200), VersionNumber int,
        DocumentStatus varchar(12)
    );
    INSERT @Listed EXEC dbo.ListInternalApplicantDocuments
        @ApplicationId=@ApplicationId,@ActorIdentity=N'cloudflare:trustee',
        @ActorGroup=N'EHF-Trustees';
    IF NOT EXISTS
        (SELECT 1 FROM @Listed WHERE DocumentSlotId=@SlotId AND DocumentVersionId=@VersionId)
        THROW 54191, 'The authorized active applicant document was not listed.', 1;

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
        @AccessPurpose='VIEW';
    IF NOT EXISTS (SELECT 1 FROM @Opened WHERE DocumentVersionId=@VersionId)
        THROW 54192, 'The authorized active applicant document could not be opened.', 1;

    EXEC dbo.RecordInternalDocumentAccessOutcome
        @ApplicationId=@ApplicationId,@DocumentVersionId=@VersionId,
        @ActorIdentity=N'cloudflare:trustee',@ActorGroup=N'EHF-Trustees',
        @AccessPurpose='VIEW',@Outcome='SUCCEEDED';
    IF (SELECT COUNT(*) FROM dbo.AuditEvent
        WHERE ApplicationId=@ApplicationId AND EntityId=@VersionId
          AND EventType IN ('INTERNAL_DOCUMENT_ACCESS_REQUESTED',
                            'INTERNAL_DOCUMENT_ACCESS_SUCCEEDED')) <> 2
        THROW 54193, 'The internal document access audit trail is incomplete.', 1;

    DECLARE @InvitationId uniqueidentifier=NEWID(), @SessionId uniqueidentifier=NEWID(),
            @PendingObjectId uniqueidentifier=NEWID(), @PendingVersionId uniqueidentifier=NEWID(),
            @SubmissionId uniqueidentifier, @SlotRowVersion binary(8),
            @DeniedVersionId uniqueidentifier=NEWID(),
            @SessionToken binary(32)=HASHBYTES('SHA2_256',N'026 session');
    INSERT dbo.ApplicantInvitation
        (ApplicantInvitationId,ApplicationId,InvitationTokenSha256,ExpiresAtUtc,CreatedByIdentity)
    VALUES
        (@InvitationId,@ApplicationId,HASHBYTES('SHA2_256',N'026 invitation'),
         DATEADD(hour,2,SYSUTCDATETIME()),N'validator');
    INSERT dbo.ApplicantSession
        (ApplicantSessionId,ApplicantInvitationId,ApplicationId,SessionTokenSha256,
         CsrfTokenSha256,CreatedAtUtc,LastSeenAtUtc,IdleExpiresAtUtc,AbsoluteExpiresAtUtc)
    VALUES
        (@SessionId,@InvitationId,@ApplicationId,@SessionToken,
         HASHBYTES('SHA2_256',N'026 csrf'),SYSUTCDATETIME(),SYSUTCDATETIME(),
         DATEADD(minute,30,SYSUTCDATETIME()),DATEADD(hour,2,SYSUTCDATETIME()));
    UPDATE dbo.DocumentSlot
    SET ApplicantUploadMode='REPLACEMENT',UploadReason=N'Validator replacement',
        OpenedByIdentity=N'validator',OpenedAtUtc=SYSUTCDATETIME()
    WHERE DocumentSlotId=@SlotId;
    SELECT @SlotRowVersion=RowVersion FROM dbo.DocumentSlot WHERE DocumentSlotId=@SlotId;

    EXEC dbo.RegisterApplicantDocumentSubmission
        @SessionTokenSha256=@SessionToken,@DocumentSlotId=@SlotId,
        @ExpectedRowVersion=@SlotRowVersion,@DocumentId=@DocumentId,
        @DocumentVersionId=@PendingVersionId,@StoredObjectId=@PendingObjectId,
        @ObjectKey='4567890abcdef1234567890abcdef123',@KeyVersion=1,@EnvelopeVersion=1,
        @AesGcmNonce=0x02030405060708090A0B0C0D,
        @PlaintextSha256=0x0202020202020202020202020202020202020202020202020202020202020202,
        @CiphertextSha256=0x0303030303030303030303030303030303030303030303030303030303030303,
        @ByteSize=124,@MediaType='application/pdf',@PageCount=1,
        @ScanEngine='validator',@ScanSignature=N'clean',
        @ScannedAtUtc='2026-09-20T00:00:00',@SubmittedDisplayName=N'pending.pdf';
    SELECT @SubmissionId=ApplicantDocumentSubmissionId
    FROM dbo.ApplicantDocumentSubmission
    WHERE DocumentVersionId=@PendingVersionId AND SubmissionStatus='PENDING';
    IF @SubmissionId IS NULL
        THROW 54194, 'The pending applicant upload was not registered.', 1;

    DELETE FROM @Opened;
    INSERT @Opened EXEC dbo.GetInternalApplicantDocument
        @ApplicationId=@ApplicationId,@DocumentVersionId=@PendingVersionId,
        @ActorIdentity=N'cloudflare:trustee',@ActorGroup=N'EHF-Trustees',
        @AccessPurpose='VIEW';
    IF NOT EXISTS (SELECT 1 FROM @Opened WHERE DocumentVersionId=@PendingVersionId)
        THROW 54195, 'The pending applicant upload could not be opened.', 1;
    EXEC dbo.RecordInternalDocumentAccessOutcome
        @ApplicationId=@ApplicationId,@DocumentVersionId=@PendingVersionId,
        @ActorIdentity=N'cloudflare:trustee',@ActorGroup=N'EHF-Trustees',
        @AccessPurpose='VIEW',@Outcome='SUCCEEDED';

    EXEC dbo.ReviewApplicantDocumentSubmission
        @ApplicantDocumentSubmissionId=@SubmissionId,@Decision='ACCEPTED',
        @ReviewedByIdentity=N'cloudflare:trustee',@ReviewerGroup='EHF-Trustees';
    IF NOT EXISTS
        (SELECT 1 FROM dbo.DocumentVersion
         WHERE DocumentVersionId=@PendingVersionId AND Classification='UNREVIEWED')
        THROW 54196, 'Acceptance unexpectedly changed applicant-upload classification.', 1;
    DELETE FROM @Listed;
    INSERT @Listed EXEC dbo.ListInternalApplicantDocuments
        @ApplicationId=@ApplicationId,@ActorIdentity=N'cloudflare:trustee',
        @ActorGroup=N'EHF-Trustees';
    IF NOT EXISTS
        (SELECT 1 FROM @Listed WHERE DocumentSlotId=@SlotId AND DocumentVersionId=@PendingVersionId)
        THROW 54197, 'The accepted applicant upload was not listed.', 1;

    DELETE FROM @Opened;
    INSERT @Opened EXEC dbo.GetInternalApplicantDocument
        @ApplicationId=@ApplicationId,@DocumentVersionId=@DeniedVersionId,
        @ActorIdentity=N'cloudflare:trustee',@ActorGroup=N'EHF-Trustees',
        @AccessPurpose='VIEW';
    IF EXISTS (SELECT 1 FROM @Opened)
        THROW 54198, 'An unknown document version was returned.', 1;
    EXEC dbo.RecordInternalDocumentAccessOutcome
        @ApplicationId=@ApplicationId,@DocumentVersionId=@DeniedVersionId,
        @ActorIdentity=N'cloudflare:trustee',@ActorGroup=N'EHF-Trustees',
        @AccessPurpose='VIEW',@Outcome='FAILED';
    IF (SELECT COUNT(*) FROM dbo.AuditEvent
        WHERE ApplicationId=@ApplicationId AND EntityId=@DeniedVersionId
          AND EventType IN ('INTERNAL_DOCUMENT_ACCESS_REQUESTED',
                            'INTERNAL_DOCUMENT_ACCESS_FAILED')) <> 2
        THROW 54199, 'The denied document access audit trail is incomplete.', 1;

    EXECUTE AS USER = N'ehf_app';
    EXEC dbo.ListInternalApplicantDocuments
        @ApplicationId=@ApplicationId,@ActorIdentity=N'cloudflare:runtime-validator',
        @ActorGroup=N'EHF-Trustees';
    REVERT;

    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF USER_NAME()=N'ehf_app' REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 026 internal document access';
