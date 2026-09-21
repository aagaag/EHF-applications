SET NOCOUNT ON;
SET XACT_ABORT ON;

EXEC(N'
ALTER PROCEDURE dbo.ListInternalApplicantDocuments
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
      AND document_row.DocumentType <> ''RECOMMENDATION_LETTER''
      AND object_row.ScanResult = ''CLEAN''
      AND NOT EXISTS
          (SELECT 1 FROM dbo.Recommendation AS recommendation_row
           WHERE recommendation_row.DocumentId = document_row.DocumentId)
      AND
      (
          (
              slot_row.ApplicantVisible = 1
              AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
              AND
              (
                  version_row.Classification = ''APPLICANT_VISIBLE''
                  OR EXISTS
                      (SELECT 1
                       FROM dbo.ApplicantDocumentSubmission AS submission_row
                       WHERE submission_row.ApplicationId = @ApplicationId
                         AND submission_row.DocumentSlotId = slot_row.DocumentSlotId
                         AND submission_row.DocumentVersionId = version_row.DocumentVersionId
                         AND submission_row.SubmissionStatus = ''ACCEPTED'')
              )
              AND
              (
                  EXISTS
                      (SELECT 1 FROM dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
                       WHERE visible_version.DocumentVersionId = version_row.DocumentVersionId)
                  OR EXISTS
                      (SELECT 1
                       FROM dbo.ApplicantDocumentSubmission AS submission_row
                       WHERE submission_row.ApplicationId = @ApplicationId
                         AND submission_row.DocumentSlotId = slot_row.DocumentSlotId
                         AND submission_row.DocumentVersionId = version_row.DocumentVersionId
                         AND submission_row.SubmissionStatus = ''ACCEPTED'')
              )
          )
          OR
          (
              slot_row.ApplicantVisible = 0
              AND slot_row.CreatedByIdentity = N''ISAB01_IMPORT''
              AND document_row.CreatedByIdentity = N''ISAB01_IMPORT''
              AND version_row.CreatedByIdentity = N''ISAB01_IMPORT''
              AND version_row.Classification = ''UNREVIEWED''
              AND NOT EXISTS
                  (SELECT 1
                   FROM dbo.SourceOccurrence AS occurrence_row
                   CROSS APPLY
                   (
                       SELECT TOP (1) decision_row.Classification
                       FROM dbo.ClassificationDecision AS decision_row
                       WHERE decision_row.SourceOccurrenceId = occurrence_row.SourceOccurrenceId
                       ORDER BY decision_row.DecidedAtUtc DESC,
                                decision_row.ClassificationDecisionId DESC
                   ) AS latest_decision
                   WHERE occurrence_row.DocumentVersionId = version_row.DocumentVersionId
                     AND latest_decision.Classification = ''CONFIDENTIAL_RECOMMENDATION'')
          )
      )
    ORDER BY slot_row.SlotCode, slot_row.DocumentSlotId;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.GetInternalApplicantDocument
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
      AND document_row.DocumentType <> ''RECOMMENDATION_LETTER''
      AND object_row.ScanResult = ''CLEAN''
      AND NOT EXISTS
          (SELECT 1 FROM dbo.Recommendation AS recommendation_row
           WHERE recommendation_row.DocumentId = document_row.DocumentId)
      AND
      (
          (
              slot_row.ApplicantVisible = 1
              AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
              AND
              (
                  version_row.Classification = ''APPLICANT_VISIBLE''
                  OR EXISTS
                      (SELECT 1
                       FROM dbo.ApplicantDocumentSubmission AS submission_row
                       WHERE submission_row.ApplicationId = @ApplicationId
                         AND submission_row.DocumentSlotId = slot_row.DocumentSlotId
                         AND submission_row.DocumentVersionId = version_row.DocumentVersionId
                         AND submission_row.SubmissionStatus IN (''PENDING'', ''ACCEPTED''))
              )
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
                            WHERE accepted_submission.ApplicationId = @ApplicationId
                              AND accepted_submission.DocumentSlotId = slot_row.DocumentSlotId
                              AND accepted_submission.DocumentVersionId = version_row.DocumentVersionId
                              AND accepted_submission.SubmissionStatus = ''ACCEPTED'')
                   ))
                  OR EXISTS
                      (SELECT 1
                       FROM dbo.ApplicantDocumentSubmission AS pending_submission
                       WHERE pending_submission.ApplicationId = @ApplicationId
                         AND pending_submission.DocumentSlotId = slot_row.DocumentSlotId
                         AND pending_submission.DocumentVersionId = version_row.DocumentVersionId
                         AND pending_submission.SubmissionStatus = ''PENDING'')
              )
          )
          OR
          (
              slot_row.ApplicantVisible = 0
              AND slot_row.ActiveDocumentVersionId = version_row.DocumentVersionId
              AND slot_row.CreatedByIdentity = N''ISAB01_IMPORT''
              AND document_row.CreatedByIdentity = N''ISAB01_IMPORT''
              AND version_row.CreatedByIdentity = N''ISAB01_IMPORT''
              AND version_row.Classification = ''UNREVIEWED''
              AND NOT EXISTS
                  (SELECT 1
                   FROM dbo.SourceOccurrence AS occurrence_row
                   CROSS APPLY
                   (
                       SELECT TOP (1) decision_row.Classification
                       FROM dbo.ClassificationDecision AS decision_row
                       WHERE decision_row.SourceOccurrenceId = occurrence_row.SourceOccurrenceId
                       ORDER BY decision_row.DecidedAtUtc DESC,
                                decision_row.ClassificationDecisionId DESC
                   ) AS latest_decision
                   WHERE occurrence_row.DocumentVersionId = version_row.DocumentVersionId
                     AND latest_decision.Classification = ''CONFIDENTIAL_RECOMMENDATION'')
          )
      );
END;
');

GRANT EXECUTE ON dbo.ListInternalApplicantDocuments TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetInternalApplicantDocument TO EHFApplicationRuntime;

PRINT 'PASS 035 internal import package';
