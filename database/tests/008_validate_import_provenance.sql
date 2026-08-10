SET NOCOUNT ON;
SET XACT_ABORT OFF;

IF OBJECT_ID(N'dbo.ImportRun', N'U') IS NULL
    THROW 51810, 'The import-run table is missing.', 1;
IF OBJECT_ID(N'dbo.ImportRow', N'U') IS NULL
    THROW 51811, 'The import-row table is missing.', 1;
IF OBJECT_ID(N'dbo.SourceOccurrence', N'U') IS NULL
    THROW 51812, 'The source-occurrence table is missing.', 1;
IF OBJECT_ID(N'dbo.CallSourceOccurrence', N'U') IS NULL
    THROW 51815, 'The call-level source-occurrence table is missing.', 1;
IF OBJECT_ID(N'dbo.ImportException', N'U') IS NULL
    THROW 51813, 'The import-exception table is missing.', 1;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallId uniqueidentifier = NEWID(), @ApplicantAId uniqueidentifier = NEWID(),
        @ApplicantBId uniqueidentifier = NEWID(), @ApplicationAId uniqueidentifier = NEWID(),
        @ApplicationBId uniqueidentifier = NEWID(), @SlotId uniqueidentifier = NEWID(),
        @DocumentId uniqueidentifier = NEWID(), @ObjectId uniqueidentifier = NEWID(),
        @VersionId uniqueidentifier = NEWID(), @RunId uniqueidentifier = NEWID();
    INSERT dbo.FellowshipCall (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
    VALUES (@CallId, N'PROV-VALIDATION', N'Synthetic provenance validation', 'OPEN', DATEADD(day, 1, SYSUTCDATETIME()));
    INSERT dbo.Applicant (ApplicantId, LegalGivenNames, LegalFamilyName)
    VALUES (@ApplicantAId, N'Provenance', N'Owner'), (@ApplicantBId, N'Provenance', N'Other');
    INSERT dbo.Application (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus)
    VALUES (@ApplicationAId, @CallId, @ApplicantAId, 'IMPORTED'),
        (@ApplicationBId, @CallId, @ApplicantBId, 'IMPORTED');
    INSERT dbo.DocumentSlot (DocumentSlotId, ApplicationId, SlotCode, CreatedByIdentity)
    VALUES (@SlotId, @ApplicationAId, 'CV', N'validator');
    INSERT dbo.Document (DocumentId, DocumentSlotId, DocumentType, CreatedByIdentity)
    VALUES (@DocumentId, @SlotId, 'CV', N'validator');
    INSERT dbo.StoredObject
        (StoredObjectId, ObjectKey, KeyVersion, EnvelopeVersion, AesGcmNonce,
         PlaintextSha256, CiphertextSha256, ByteSize, MediaType, PageCount,
         ScanEngine, ScannedAtUtc, ScanResult, CreatedByIdentity)
    VALUES
        (@ObjectId, '1234567890abcdef1234567890abcdef', 1, 1, CONVERT(binary(12), 0x0102030405060708090A0B0C),
         HASHBYTES('SHA2_256', N'provenance-plain'), HASHBYTES('SHA2_256', N'provenance-cipher'), 1, 'application/pdf', 1,
         'validator', SYSUTCDATETIME(), 'CLEAN', N'validator');
    INSERT dbo.DocumentVersion (DocumentVersionId, DocumentId, StoredObjectId, VersionNumber, Classification, CreatedByIdentity)
    VALUES (@VersionId, @DocumentId, @ObjectId, 1, 'UNREVIEWED', N'validator');
    UPDATE dbo.DocumentSlot SET ActiveDocumentVersionId = @VersionId WHERE DocumentSlotId = @SlotId;
    INSERT dbo.ImportRun (ImportRunId, FellowshipCallId, ImportFingerprintSha256, ImporterVersion, RunStatus, StartedByIdentity)
    VALUES (@RunId, @CallId, HASHBYTES('SHA2_256', N'provenance-run'), 'validator', 'PLANNED', N'validator');

    -- SUCCESSFUL VALIDATOR WRITE: non-document occurrence permits null version
    INSERT dbo.SourceOccurrence
        (SourceOccurrenceId, ImportRunId, ApplicationId, DocumentVersionId,
         SourceLocatorSha256, SourceContentSha256, SourceByteSize, ImportDisposition)
    VALUES
        (NEWID(), @RunId, @ApplicationBId, NULL,
         HASHBYTES('SHA2_256', N'non-document-locator'), HASHBYTES('SHA2_256', N'non-document-content'), 1, 'NON_PDF');

    INSERT dbo.CallSourceOccurrence
        (ImportRunId, SourceLocatorSha256, SourceContentSha256, SourceByteSize, ImportDisposition)
    VALUES
        (@RunId, HASHBYTES('SHA2_256', N'internal-locator'), HASHBYTES('SHA2_256', N'internal-content'), 1,
         'REVIEWED_INTERNAL_EXCLUSION');

    -- ISOLATED EXPECTED FAILURE: linked version belongs to another application
    BEGIN TRY
        INSERT dbo.SourceOccurrence
            (SourceOccurrenceId, ImportRunId, ApplicationId, DocumentVersionId,
             SourceLocatorSha256, SourceContentSha256, SourceByteSize, ImportDisposition)
        VALUES
            (NEWID(), @RunId, @ApplicationBId, @VersionId,
             HASHBYTES('SHA2_256', N'wrong-owner-locator'), HASHBYTES('SHA2_256', N'wrong-owner-content'), 1, 'INGESTED');
        THROW 51814, 'A source occurrence linked a version owned by another application.', 1;
    END TRY
    BEGIN CATCH
        DECLARE @OwnershipError int = ERROR_NUMBER();
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        IF @OwnershipError <> 51712 THROW;
    END CATCH;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 008 import provenance';
