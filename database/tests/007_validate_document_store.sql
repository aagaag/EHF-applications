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

EXEC(N'
CREATE PROCEDURE #CreateDocumentFixture
    @DocumentId uniqueidentifier OUTPUT,
    @VersionId uniqueidentifier OUTPUT,
    @RecommendationId uniqueidentifier OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @CallId uniqueidentifier = NEWID(), @ApplicantId uniqueidentifier = NEWID(),
        @ApplicationId uniqueidentifier = NEWID(), @SlotId uniqueidentifier = NEWID(),
        @ObjectId uniqueidentifier = NEWID(), @RecommendationSlotId uniqueidentifier = NEWID(),
        @RecommendationDocumentId uniqueidentifier = NEWID();
    SET @DocumentId = NEWID();
    SET @VersionId = NEWID();
    SET @RecommendationId = NEWID();
    INSERT dbo.FellowshipCall (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
    VALUES (@CallId, CONCAT(N''DOC-VAL-'', REPLACE(CONVERT(nvarchar(36), @CallId), ''-'', '''')),
            N''Synthetic document validation'', ''OPEN'', DATEADD(day, 1, SYSUTCDATETIME()));
    INSERT dbo.Applicant (ApplicantId, LegalGivenNames, LegalFamilyName)
    VALUES (@ApplicantId, N''Synthetic'', N''Document'');
    INSERT dbo.Application (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus)
    VALUES (@ApplicationId, @CallId, @ApplicantId, ''IMPORTED'');
    INSERT dbo.DocumentSlot (DocumentSlotId, ApplicationId, SlotCode, CreatedByIdentity)
    VALUES (@SlotId, @ApplicationId, ''CV'', N''validator'');
    INSERT dbo.Document (DocumentId, DocumentSlotId, DocumentType, CreatedByIdentity)
    VALUES (@DocumentId, @SlotId, ''CV'', N''validator'');
    INSERT dbo.StoredObject
        (StoredObjectId, ObjectKey, KeyVersion, EnvelopeVersion, AesGcmNonce,
         PlaintextSha256, CiphertextSha256, ByteSize, MediaType, PageCount,
         ScanEngine, ScannedAtUtc, ScanResult, CreatedByIdentity)
    VALUES
        (@ObjectId, REPLACE(CONVERT(varchar(36), @ObjectId), ''-'', ''''), 1, 1,
         CONVERT(binary(12), 0x0102030405060708090A0B0C), HASHBYTES(''SHA2_256'', CONVERT(nvarchar(36), @ObjectId)),
         HASHBYTES(''SHA2_256'', CONVERT(nvarchar(36), @VersionId)), 1, ''application/pdf'', 1,
         ''validator'', SYSUTCDATETIME(), ''CLEAN'', N''validator'');
    INSERT dbo.DocumentVersion (DocumentVersionId, DocumentId, StoredObjectId, VersionNumber, Classification, CreatedByIdentity)
    VALUES (@VersionId, @DocumentId, @ObjectId, 1, ''UNREVIEWED'', N''validator'');
    UPDATE dbo.DocumentSlot SET ActiveDocumentVersionId = @VersionId WHERE DocumentSlotId = @SlotId;
    INSERT dbo.DocumentSlot (DocumentSlotId, ApplicationId, SlotCode, CreatedByIdentity)
    VALUES (@RecommendationSlotId, @ApplicationId, ''RECOMMENDATION'', N''validator'');
    INSERT dbo.Document (DocumentId, DocumentSlotId, DocumentType, CreatedByIdentity)
    VALUES (@RecommendationDocumentId, @RecommendationSlotId, ''RECOMMENDATION_LETTER'', N''validator'');
    INSERT dbo.Recommendation (RecommendationId, DocumentId, ArrivalChannel, CreatedByIdentity)
    VALUES (@RecommendationId, @RecommendationDocumentId, ''DIRECT_REFEREE'', N''validator'');
END;
');

DECLARE @DocumentId uniqueidentifier, @VersionId uniqueidentifier, @RecommendationId uniqueidentifier;

-- ISOLATED EXPECTED FAILURE: document type is immutable
BEGIN TRANSACTION;
EXEC #CreateDocumentFixture @DocumentId OUTPUT, @VersionId OUTPUT, @RecommendationId OUTPUT;
BEGIN TRY
    UPDATE dbo.Document SET DocumentType = 'OTHER' WHERE DocumentId = @DocumentId;
    THROW 51806, 'A document type was mutable.', 1;
END TRY
BEGIN CATCH
    DECLARE @DocumentTypeError int = ERROR_NUMBER();
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    IF @DocumentTypeError <> 51703 THROW;
END CATCH;
IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;

-- ISOLATED EXPECTED FAILURE: recommendation link requires recommendation document type
BEGIN TRANSACTION;
EXEC #CreateDocumentFixture @DocumentId OUTPUT, @VersionId OUTPUT, @RecommendationId OUTPUT;
BEGIN TRY
    INSERT dbo.Recommendation (RecommendationId, DocumentId, ArrivalChannel, CreatedByIdentity)
    VALUES (NEWID(), @DocumentId, 'DIRECT_REFEREE', N'validator');
    THROW 51807, 'A recommendation linked to a non-recommendation document type.', 1;
END TRY
BEGIN CATCH
    DECLARE @RecommendationTypeError int = ERROR_NUMBER();
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    IF @RecommendationTypeError <> 51705 THROW;
END CATCH;
IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;

-- ISOLATED EXPECTED FAILURE: recommendation link is immutable
BEGIN TRANSACTION;
EXEC #CreateDocumentFixture @DocumentId OUTPUT, @VersionId OUTPUT, @RecommendationId OUTPUT;
BEGIN TRY
    UPDATE dbo.Recommendation SET ArrivalChannel = 'APPLICANT_FORWARDED'
    WHERE RecommendationId = @RecommendationId;
    THROW 51808, 'A recommendation link was mutable.', 1;
END TRY
BEGIN CATCH
    DECLARE @RecommendationImmutableError int = ERROR_NUMBER();
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    IF @RecommendationImmutableError <> 51704 THROW;
END CATCH;
IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;

-- ISOLATED EXPECTED FAILURE: document version is immutable
BEGIN TRANSACTION;
EXEC #CreateDocumentFixture @DocumentId OUTPUT, @VersionId OUTPUT, @RecommendationId OUTPUT;
BEGIN TRY
    UPDATE dbo.DocumentVersion SET VersionNumber = 2 WHERE DocumentVersionId = @VersionId;
    THROW 51805, 'A document version was mutable.', 1;
END TRY
BEGIN CATCH
    DECLARE @DocumentVersionError int = ERROR_NUMBER();
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    IF @DocumentVersionError <> 51702 THROW;
END CATCH;
IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;

PRINT 'PASS 007 document store';
