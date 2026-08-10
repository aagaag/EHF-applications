SET NOCOUNT ON;
SET XACT_ABORT OFF;

IF OBJECT_ID(N'dbo.DocumentSlot', N'U') IS NULL
    THROW 51800, 'The document-slot table is missing.', 1;
IF OBJECT_ID(N'dbo.Document', N'U') IS NULL
    THROW 51801, 'The document table is missing.', 1;
IF OBJECT_ID(N'dbo.DocumentVersion', N'U') IS NULL
    THROW 51802, 'The document-version table is missing.', 1;
IF OBJECT_ID(N'dbo.StoredObject', N'U') IS NULL
    THROW 51803, 'The stored-object table is missing.', 1;
IF OBJECT_ID(N'dbo.Recommendation', N'U') IS NULL
    THROW 51804, 'The recommendation table is missing.', 1;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallId uniqueidentifier = NEWID(), @ApplicantId uniqueidentifier = NEWID(),
        @ApplicationId uniqueidentifier = NEWID(), @SlotId uniqueidentifier = NEWID(),
        @DocumentId uniqueidentifier = NEWID(), @ObjectId uniqueidentifier = NEWID(),
        @VersionId uniqueidentifier = NEWID();
    INSERT dbo.FellowshipCall (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
    VALUES (@CallId, N'DOC-VALIDATION', N'Synthetic document validation', 'OPEN', DATEADD(day, 1, SYSUTCDATETIME()));
    INSERT dbo.Applicant (ApplicantId, LegalGivenNames, LegalFamilyName)
    VALUES (@ApplicantId, N'Synthetic', N'Document');
    INSERT dbo.Application (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus)
    VALUES (@ApplicationId, @CallId, @ApplicantId, 'IMPORTED');
    INSERT dbo.DocumentSlot (DocumentSlotId, ApplicationId, SlotCode, CreatedByIdentity)
    VALUES (@SlotId, @ApplicationId, 'CV', N'validator');
    INSERT dbo.Document (DocumentId, DocumentSlotId, DocumentType, CreatedByIdentity)
    VALUES (@DocumentId, @SlotId, 'CV', N'validator');
    INSERT dbo.StoredObject
        (StoredObjectId, ObjectKey, KeyVersion, EnvelopeVersion, AesGcmNonce,
         PlaintextSha256, CiphertextSha256, ByteSize, MediaType, PageCount,
         ScanEngine, ScannedAtUtc, ScanResult, CreatedByIdentity)
    VALUES
        (@ObjectId, '0123456789abcdef0123456789abcdef', 1, 1, CONVERT(binary(12), 0x0102030405060708090A0B0C),
         HASHBYTES('SHA2_256', N'plain'), HASHBYTES('SHA2_256', N'cipher'), 1, 'application/pdf', 1,
         'validator', SYSUTCDATETIME(), 'CLEAN', N'validator');
    INSERT dbo.DocumentVersion (DocumentVersionId, DocumentId, StoredObjectId, VersionNumber, Classification, CreatedByIdentity)
    VALUES (@VersionId, @DocumentId, @ObjectId, 1, 'UNREVIEWED', N'validator');
    UPDATE dbo.DocumentSlot SET ActiveDocumentVersionId = @VersionId WHERE DocumentSlotId = @SlotId;

    -- ISOLATED EXPECTED FAILURE: document type is immutable
    BEGIN TRY
        UPDATE dbo.Document SET DocumentType = 'OTHER' WHERE DocumentId = @DocumentId;
        THROW 51806, 'A document type was mutable.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() <> 51703 THROW;
    END CATCH;

    -- ISOLATED EXPECTED FAILURE: recommendation link requires recommendation document type
    BEGIN TRY
        INSERT dbo.Recommendation (RecommendationId, DocumentId, ArrivalChannel, CreatedByIdentity)
        VALUES (NEWID(), @DocumentId, 'DIRECT_REFEREE', N'validator');
        THROW 51807, 'A recommendation linked to a non-recommendation document type.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() <> 51705 THROW;
    END CATCH;

    DECLARE @RecommendationSlotId uniqueidentifier = NEWID(),
        @RecommendationDocumentId uniqueidentifier = NEWID(),
        @RecommendationId uniqueidentifier = NEWID();
    INSERT dbo.DocumentSlot (DocumentSlotId, ApplicationId, SlotCode, CreatedByIdentity)
    VALUES (@RecommendationSlotId, @ApplicationId, 'RECOMMENDATION', N'validator');
    INSERT dbo.Document (DocumentId, DocumentSlotId, DocumentType, CreatedByIdentity)
    VALUES (@RecommendationDocumentId, @RecommendationSlotId, 'RECOMMENDATION_LETTER', N'validator');
    INSERT dbo.Recommendation (RecommendationId, DocumentId, ArrivalChannel, CreatedByIdentity)
    VALUES (@RecommendationId, @RecommendationDocumentId, 'DIRECT_REFEREE', N'validator');

    -- ISOLATED EXPECTED FAILURE: recommendation link is immutable
    BEGIN TRY
        UPDATE dbo.Recommendation
        SET ArrivalChannel = 'APPLICANT_FORWARDED'
        WHERE RecommendationId = @RecommendationId;
        THROW 51808, 'A recommendation link was mutable.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() <> 51704 THROW;
    END CATCH;

    BEGIN TRY
        UPDATE dbo.DocumentVersion SET VersionNumber = 2 WHERE DocumentVersionId = @VersionId;
        THROW 51805, 'A document version was mutable.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() <> 51702 THROW;
    END CATCH;

    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 007 document store';
