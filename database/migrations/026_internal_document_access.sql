SET NOCOUNT ON;
SET XACT_ABORT ON;

EXEC(N'
CREATE PROCEDURE dbo.ListInternalApplicantDocuments
    @ApplicationId uniqueidentifier,
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    IF @ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')
       OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
        THROW 54110, ''Administrator or trustee authorization is required.'', 1;

    SELECT slot_row.DocumentSlotId, version_row.DocumentVersionId,
           slot_row.SlotCode, slot_row.SlotLabel, version_row.VersionNumber,
           CONVERT(varchar(12), ''ACCEPTED'') AS DocumentStatus
    FROM dbo.DocumentSlot AS slot_row
    JOIN dbo.Document AS document_row
      ON document_row.DocumentSlotId = slot_row.DocumentSlotId
    JOIN dbo.DocumentVersion AS version_row
      ON version_row.DocumentVersionId = slot_row.ActiveDocumentVersionId
     AND version_row.DocumentId = document_row.DocumentId
    JOIN dbo.StoredObject AS object_row
      ON object_row.StoredObjectId = version_row.StoredObjectId
    WHERE slot_row.ApplicationId = @ApplicationId
      AND slot_row.ApplicantVisible = 1
      AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
      AND document_row.DocumentType <> ''RECOMMENDATION_LETTER''
      AND version_row.Classification = ''APPLICANT_VISIBLE''
      AND object_row.ScanResult = ''CLEAN''
      AND NOT EXISTS
          (SELECT 1 FROM dbo.Recommendation AS recommendation_row
           WHERE recommendation_row.DocumentId = document_row.DocumentId)
      AND
      (
          EXISTS
              (SELECT 1 FROM dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
               WHERE visible_version.DocumentVersionId = version_row.DocumentVersionId)
          OR EXISTS
              (SELECT 1
               FROM dbo.ApplicantDocumentSubmission AS submission_row
               JOIN dbo.ApplicantDocumentReviewDecision AS decision_row
                 ON decision_row.ApplicantDocumentSubmissionId =
                    submission_row.ApplicantDocumentSubmissionId
                AND decision_row.ReviewDecision = ''ACCEPTED''
               WHERE submission_row.DocumentVersionId = version_row.DocumentVersionId)
      )
    ORDER BY slot_row.SlotCode, slot_row.DocumentSlotId;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetInternalApplicantDocument
    @ApplicationId uniqueidentifier,
    @DocumentVersionId uniqueidentifier,
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128),
    @AccessPurpose varchar(12)
AS
BEGIN
    SET NOCOUNT ON;
    IF @ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')
       OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
       OR @AccessPurpose NOT IN (''VIEW'', ''DOWNLOAD'', ''PACKAGE'')
        THROW 54110, ''Administrator or trustee authorization is required.'', 1;

    IF EXISTS (SELECT 1 FROM dbo.Application WHERE ApplicationId = @ApplicationId)
        INSERT dbo.AuditEvent
            (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
        VALUES
            (@ApplicationId, ''INTERNAL_DOCUMENT_ACCESS_REQUESTED'',
             LTRIM(RTRIM(@ActorIdentity)), ''DocumentVersion'', @DocumentVersionId,
             (SELECT @ActorGroup AS actorGroup, @AccessPurpose AS purpose
              FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));

    SELECT slot_row.ApplicationId, document_row.DocumentId,
           version_row.DocumentVersionId, object_row.StoredObjectId,
           object_row.ObjectKey, object_row.KeyVersion, object_row.EnvelopeVersion,
           object_row.AesGcmNonce, object_row.PlaintextSha256,
           object_row.CiphertextSha256, object_row.ByteSize
    FROM dbo.DocumentSlot AS slot_row
    JOIN dbo.Document AS document_row
      ON document_row.DocumentSlotId = slot_row.DocumentSlotId
    JOIN dbo.DocumentVersion AS version_row
      ON version_row.DocumentId = document_row.DocumentId
     AND version_row.DocumentVersionId = @DocumentVersionId
    JOIN dbo.StoredObject AS object_row
      ON object_row.StoredObjectId = version_row.StoredObjectId
    WHERE slot_row.ApplicationId = @ApplicationId
      AND slot_row.ApplicantVisible = 1
      AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
      AND document_row.DocumentType <> ''RECOMMENDATION_LETTER''
      AND version_row.Classification = ''APPLICANT_VISIBLE''
      AND object_row.ScanResult = ''CLEAN''
      AND NOT EXISTS
          (SELECT 1 FROM dbo.Recommendation AS recommendation_row
           WHERE recommendation_row.DocumentId = document_row.DocumentId)
      AND
      (
          (slot_row.ActiveDocumentVersionId = version_row.DocumentVersionId
           AND
           (
               EXISTS
                   (SELECT 1 FROM dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
                    WHERE visible_version.DocumentVersionId = version_row.DocumentVersionId)
               OR EXISTS
                   (SELECT 1
                    FROM dbo.ApplicantDocumentSubmission AS accepted_submission
                    JOIN dbo.ApplicantDocumentReviewDecision AS accepted_decision
                      ON accepted_decision.ApplicantDocumentSubmissionId =
                         accepted_submission.ApplicantDocumentSubmissionId
                     AND accepted_decision.ReviewDecision = ''ACCEPTED''
                    WHERE accepted_submission.DocumentVersionId =
                          version_row.DocumentVersionId)
           ))
          OR EXISTS
              (SELECT 1
               FROM dbo.ApplicantDocumentSubmission AS pending_submission
               WHERE pending_submission.ApplicationId = @ApplicationId
                 AND pending_submission.DocumentSlotId = slot_row.DocumentSlotId
                 AND pending_submission.DocumentVersionId = version_row.DocumentVersionId
                 AND pending_submission.SubmissionStatus = ''PENDING'')
      );
END;
');

EXEC(N'
CREATE PROCEDURE dbo.RecordInternalDocumentAccessOutcome
    @ApplicationId uniqueidentifier,
    @DocumentVersionId uniqueidentifier,
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128),
    @AccessPurpose varchar(12),
    @Outcome varchar(12)
AS
BEGIN
    SET NOCOUNT ON;
    IF @ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')
       OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
       OR @AccessPurpose NOT IN (''VIEW'', ''DOWNLOAD'', ''PACKAGE'')
       OR @Outcome NOT IN (''SUCCEEDED'', ''FAILED'')
        THROW 54111, ''A valid document-access outcome is required.'', 1;

    IF EXISTS (SELECT 1 FROM dbo.Application WHERE ApplicationId = @ApplicationId)
        INSERT dbo.AuditEvent
            (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
        VALUES
            (@ApplicationId,
             CASE @Outcome WHEN ''SUCCEEDED'' THEN ''INTERNAL_DOCUMENT_ACCESS_SUCCEEDED''
                           ELSE ''INTERNAL_DOCUMENT_ACCESS_FAILED'' END,
             LTRIM(RTRIM(@ActorIdentity)), ''DocumentVersion'', @DocumentVersionId,
             (SELECT @ActorGroup AS actorGroup, @AccessPurpose AS purpose,
                     @Outcome AS outcome
              FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));
END;
');

GRANT EXECUTE ON dbo.ListInternalApplicantDocuments TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetInternalApplicantDocument TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.RecordInternalDocumentAccessOutcome TO EHFApplicationRuntime;
