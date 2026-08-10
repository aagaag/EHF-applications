SET NOCOUNT ON;
SET XACT_ABORT OFF;

IF OBJECT_ID(N'dbo.ClassificationDecision', N'U') IS NULL
    THROW 51820, 'The classification-decision table is missing.', 1;
IF OBJECT_ID(N'dbo.vw_ApplicantVisibleDocumentVersion', N'V') IS NULL
    THROW 51821, 'The applicant-visible document projection is missing.', 1;
IF OBJECT_ID(N'dbo.vw_InternalDocumentVersion', N'V') IS NULL
    THROW 51822, 'The internal document projection is missing.', 1;
IF OBJECT_ID(N'dbo.ValidateApplicationInvitation', N'P') IS NULL
    THROW 51823, 'The pre-invitation validation procedure is missing.', 1;
IF OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P') IS NULL
    THROW 51827, 'The role-scoped internal metrics procedure is missing.', 1;

IF NOT EXISTS
(
    SELECT 1
    FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND class = 1
      AND major_id = OBJECT_ID(N'dbo.vw_InternalDocumentVersion', N'V')
      AND permission_name = N'SELECT'
      AND state_desc = N'DENY'
)
    THROW 51824, 'The runtime role must not read the internal document projection.', 1;

IF NOT EXISTS
(
    SELECT 1
    FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND class = 1
      AND major_id = OBJECT_ID(N'dbo.GetInternalApplicationMetrics', N'P')
      AND permission_name = N'EXECUTE'
      AND state_desc = N'GRANT'
)
    THROW 51828, 'The runtime role must execute only the role-scoped metrics procedure.', 1;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallId uniqueidentifier = NEWID(), @ApplicantId uniqueidentifier = NEWID(),
        @ApplicationId uniqueidentifier = NEWID(), @SlotId uniqueidentifier = NEWID(),
        @DocumentId uniqueidentifier = NEWID(), @ObjectId uniqueidentifier = NEWID(),
        @VersionId uniqueidentifier = NEWID(), @RecommendationId uniqueidentifier = NEWID(),
        @RunId uniqueidentifier = NEWID(), @OccurrenceId uniqueidentifier = NEWID();
    INSERT dbo.FellowshipCall (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
    VALUES (@CallId, N'PERM-VALIDATION', N'Synthetic permissions validation', 'OPEN', DATEADD(day, 1, SYSUTCDATETIME()));
    INSERT dbo.Applicant (ApplicantId, LegalGivenNames, LegalFamilyName)
    VALUES (@ApplicantId, N'Permission', N'Validator');
    INSERT dbo.Application (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus)
    VALUES (@ApplicationId, @CallId, @ApplicantId, 'IMPORTED');
    INSERT dbo.DocumentSlot (DocumentSlotId, ApplicationId, SlotCode, CreatedByIdentity)
    VALUES (@SlotId, @ApplicationId, 'RECOMMENDATION', N'validator');
    INSERT dbo.Document (DocumentId, DocumentSlotId, DocumentType, CreatedByIdentity)
    VALUES (@DocumentId, @SlotId, 'RECOMMENDATION_LETTER', N'validator');
    INSERT dbo.StoredObject
        (StoredObjectId, ObjectKey, KeyVersion, EnvelopeVersion, AesGcmNonce,
         PlaintextSha256, CiphertextSha256, ByteSize, MediaType, PageCount,
         ScanEngine, ScannedAtUtc, ScanResult, CreatedByIdentity)
    VALUES
        (@ObjectId, '234567890abcdef1234567890abcdef1', 1, 1, CONVERT(binary(12), 0x0102030405060708090A0B0C),
         HASHBYTES('SHA2_256', N'permissions-plain'), HASHBYTES('SHA2_256', N'permissions-cipher'), 1, 'application/pdf', 1,
         'validator', SYSUTCDATETIME(), 'CLEAN', N'validator');
    INSERT dbo.DocumentVersion (DocumentVersionId, DocumentId, StoredObjectId, VersionNumber, Classification, CreatedByIdentity)
    VALUES (@VersionId, @DocumentId, @ObjectId, 1, 'UNREVIEWED', N'validator');
    UPDATE dbo.DocumentSlot SET ActiveDocumentVersionId = @VersionId WHERE DocumentSlotId = @SlotId;
    INSERT dbo.Recommendation (RecommendationId, DocumentId, ArrivalChannel, CreatedByIdentity)
    VALUES (@RecommendationId, @DocumentId, 'DIRECT_REFEREE', N'validator');
    INSERT dbo.ImportRun (ImportRunId, FellowshipCallId, ImportFingerprintSha256, ImporterVersion, RunStatus, StartedByIdentity)
    VALUES (@RunId, @CallId, HASHBYTES('SHA2_256', N'permissions-run'), 'validator', 'PLANNED', N'validator');
    INSERT dbo.SourceOccurrence
        (SourceOccurrenceId, ImportRunId, ApplicationId, DocumentVersionId,
         SourceLocatorSha256, SourceContentSha256, SourceByteSize, ImportDisposition)
    VALUES
        (@OccurrenceId, @RunId, @ApplicationId, @VersionId,
         HASHBYTES('SHA2_256', N'permissions-locator'), HASHBYTES('SHA2_256', N'permissions-content'), 1, 'INGESTED');

    INSERT dbo.ClassificationDecision (SourceOccurrenceId, Classification, Reason, DecidedByIdentity)
    VALUES (@OccurrenceId, 'CONFIDENTIAL_RECOMMENDATION', N'Confidential recommendation test fixture.', N'validator');

    -- SUCCESSFUL VALIDATOR ASSERTION: linked recommendation is excluded from applicant projection
    IF EXISTS
    (
        SELECT 1
        FROM dbo.vw_ApplicantVisibleDocumentVersion
        WHERE DocumentVersionId = @VersionId
    )
        THROW 51826, 'A linked recommendation appeared in the applicant projection.', 1;

    -- ISOLATED EXPECTED FAILURE: linked recommendation cannot be applicant-visible
    BEGIN TRY
        INSERT dbo.ClassificationDecision (SourceOccurrenceId, Classification, DecidedByIdentity)
        VALUES (@OccurrenceId, 'APPLICANT_VISIBLE', N'validator');
        THROW 51825, 'A linked recommendation was classified applicant-visible.', 1;
    END TRY
    BEGIN CATCH
        DECLARE @RecommendationVisibilityError int = ERROR_NUMBER();
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        IF @RecommendationVisibilityError <> 51721 THROW;
    END CATCH;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 009 document permissions';
