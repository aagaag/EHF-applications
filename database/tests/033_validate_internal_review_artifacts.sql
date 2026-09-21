SET NOCOUNT ON;
SET XACT_ABORT OFF;

IF OBJECT_ID(N'dbo.InternalReviewArtifactProvenance', N'U') IS NULL
    THROW 54130, 'The internal review artifact provenance table is missing.', 1;
IF OBJECT_ID(N'dbo.TR_InternalReviewArtifactProvenance_AppendOnly', N'TR') IS NULL
    THROW 54131, 'The internal review artifact append-only trigger is missing.', 1;
IF OBJECT_ID(N'dbo.ListInternalReviewArtifacts', N'P') IS NULL
   OR OBJECT_ID(N'dbo.GetInternalReviewArtifact', N'P') IS NULL
   OR OBJECT_ID(N'dbo.RecordInternalReviewArtifactFailure', N'P') IS NULL
    THROW 54132, 'The internal review artifact procedures are missing.', 1;
IF dbo.IsAuditPayloadKeyProhibited(N'category') <> 0
    THROW 54134, 'The review-artifact audit category is not allowlisted.', 1;
IF dbo.IsAuditPayloadKeyProhibited(N'applicantEmail') <> 1
    THROW 54135, 'A sensitive review-artifact audit key was accepted.', 1;

IF EXISTS
(
    SELECT 1
    FROM sys.database_permissions AS permission_row
    WHERE permission_row.grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND permission_row.major_id = OBJECT_ID(N'dbo.InternalReviewArtifactProvenance')
      AND permission_row.permission_name IN (N'SELECT', N'INSERT', N'UPDATE', N'DELETE')
      AND permission_row.state_desc <> N'DENY'
)
    THROW 54133, 'The runtime can directly access artifact provenance.', 1;

BEGIN TRANSACTION;
DECLARE @CallId uniqueidentifier='33000000-0000-4000-8000-000000000001';
DECLARE @ApplicantId uniqueidentifier='33000000-0000-4000-8000-000000000002';
DECLARE @ApplicationId uniqueidentifier='33000000-0000-4000-8000-000000000003';
DECLARE @SlotId uniqueidentifier='33000000-0000-4000-8000-000000000004';
DECLARE @DocumentId uniqueidentifier='33000000-0000-4000-8000-000000000005';
DECLARE @ObjectId uniqueidentifier='33000000-0000-4000-8000-000000000006';
DECLARE @VersionId uniqueidentifier='33000000-0000-4000-8000-000000000007';

INSERT dbo.FellowshipCall
    (FellowshipCallId,CallCode,DisplayName,CallStatus,ApplicationDeadlineUtc)
VALUES (@CallId,N'VALIDATE-033',N'Validate review artifacts','DRAFT','2030-01-01');
INSERT dbo.Applicant (ApplicantId,LegalGivenNames,LegalFamilyName)
VALUES (@ApplicantId,N'Validation',N'Applicant');
INSERT dbo.Application
    (ApplicationId,FellowshipCallId,ApplicantId,ApplicationStatus)
VALUES (@ApplicationId,@CallId,@ApplicantId,'IMPORTED');
INSERT dbo.DocumentSlot
    (DocumentSlotId,ApplicationId,SlotCode,CreatedByIdentity,ApplicantUploadMode,
     ApplicantVisible,SlotLabel,RequiredForCompletion)
VALUES (@SlotId,@ApplicationId,'REVIEW-ARTIFACT-APPLICATION',N'validator','CLOSED',
        0,N'Reviewed fellowship application',0);
INSERT dbo.Document (DocumentId,DocumentSlotId,DocumentType,CreatedByIdentity)
VALUES (@DocumentId,@SlotId,'RESEARCH_PLAN',N'validator');
INSERT dbo.StoredObject
    (StoredObjectId,ObjectKey,KeyVersion,EnvelopeVersion,AesGcmNonce,
     PlaintextSha256,CiphertextSha256,ByteSize,MediaType,PageCount,
     ScanEngine,ScannedAtUtc,ScanResult,CreatedByIdentity)
VALUES (@ObjectId,'33000000000000000000000000000006',1,1,
        0x000000000000000000000000,
        0x0000000000000000000000000000000000000000000000000000000000000001,
        0x0000000000000000000000000000000000000000000000000000000000000002,
        1,'application/pdf',1,'validator',SYSUTCDATETIME(),'CLEAN',N'validator');
INSERT dbo.DocumentVersion
    (DocumentVersionId,DocumentId,StoredObjectId,VersionNumber,Classification,CreatedByIdentity)
VALUES (@VersionId,@DocumentId,@ObjectId,1,'INTERNAL_ADMINISTRATIVE',N'validator');
UPDATE dbo.DocumentSlot SET ActiveDocumentVersionId=@VersionId WHERE DocumentSlotId=@SlotId;
INSERT dbo.InternalReviewArtifactProvenance
    (ApplicationId,Category,ArtifactDocumentVersionId,SourceDocumentVersionId,
     SegmentOrder,FirstPage,LastPage,SourcePlaintextSha256,ReviewedByIdentity)
VALUES (@ApplicationId,'APPLICATION',@VersionId,@VersionId,1,1,1,
        0x0000000000000000000000000000000000000000000000000000000000000001,
        N'validator');

EXEC dbo.GetInternalReviewArtifact
    @ApplicationId=@ApplicationId,@Category='APPLICATION',
    @ActorIdentity=N'validator',@ActorGroup=N'EHF-Trustees';
IF NOT EXISTS
(
    SELECT 1 FROM dbo.AuditEvent
    WHERE ApplicationId=@ApplicationId
      AND EventType='INTERNAL_DOCUMENT_ACCESS_REQUESTED'
      AND JSON_VALUE(PayloadJson,'$.category')='APPLICATION'
)
    THROW 54136, 'The successful category lookup was not audited.', 1;

EXEC dbo.RecordInternalReviewArtifactFailure
    @ApplicationId=@ApplicationId,@Category='CURRICULUM',
    @ActorIdentity=N'validator',@ActorGroup=N'EHF-Trustees';
IF (SELECT COUNT_BIG(*) FROM dbo.AuditEvent
    WHERE ApplicationId=@ApplicationId
      AND EventType IN ('INTERNAL_DOCUMENT_ACCESS_REQUESTED','INTERNAL_DOCUMENT_ACCESS_FAILED')
      AND JSON_VALUE(PayloadJson,'$.category')='CURRICULUM') <> 2
    THROW 54137, 'The failed category lookup was not fully audited.', 1;
ROLLBACK TRANSACTION;

BEGIN TRY
    EXECUTE AS USER = N'ehf_app';
    EXEC dbo.ListInternalReviewArtifacts
        @ApplicationId='00000000-0000-0000-0000-000000000000',
        @ActorIdentity=N'validator', @ActorGroup=N'EHF-Trustees';
    REVERT;
END TRY
BEGIN CATCH
    IF USER_NAME() = N'ehf_app' REVERT;
    THROW;
END CATCH;

PRINT 'PASS 033 internal review artifacts';
