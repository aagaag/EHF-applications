SET NOCOUNT ON;
SET XACT_ABORT ON;

ALTER TABLE dbo.ApplicantContact
    ADD ReviewStatus varchar(12) NOT NULL
        CONSTRAINT DF_ApplicantContact_ReviewStatus DEFAULT 'UNREVIEWED',
        ReviewedByIdentity nvarchar(255) NULL,
        ReviewedAtUtc datetime2(7) NULL;

ALTER TABLE dbo.ApplicantContact
    ADD CONSTRAINT CK_ApplicantContact_ReviewStatus CHECK
        (ReviewStatus IN ('UNREVIEWED', 'REVIEWED')),
        CONSTRAINT CK_ApplicantContact_ReviewEvidence CHECK
        ((ReviewStatus = 'UNREVIEWED' AND ReviewedByIdentity IS NULL AND ReviewedAtUtc IS NULL)
         OR (ReviewStatus = 'REVIEWED' AND LEN(ReviewedByIdentity) > 0 AND ReviewedAtUtc IS NOT NULL));

CREATE TABLE dbo.ClassificationDecision
(
    ClassificationDecisionId uniqueidentifier NOT NULL
        CONSTRAINT DF_ClassificationDecision_Id DEFAULT NEWSEQUENTIALID(),
    SourceOccurrenceId uniqueidentifier NOT NULL,
    Classification varchar(40) NOT NULL,
    Reason nvarchar(1000) NULL,
    DecidedByIdentity nvarchar(255) NOT NULL,
    DecidedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ClassificationDecision_DecidedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ClassificationDecision PRIMARY KEY (ClassificationDecisionId),
    CONSTRAINT FK_ClassificationDecision_Occurrence FOREIGN KEY (SourceOccurrenceId)
        REFERENCES dbo.SourceOccurrence (SourceOccurrenceId),
    CONSTRAINT CK_ClassificationDecision_Class CHECK (Classification IN
        ('UNREVIEWED', 'APPLICANT_VISIBLE', 'CONFIDENTIAL_RECOMMENDATION',
         'INTERNAL_ADMINISTRATIVE')),
    CONSTRAINT CK_ClassificationDecision_Actor CHECK (LEN(DecidedByIdentity) > 0),
    CONSTRAINT CK_ClassificationDecision_Reason CHECK
        (Classification <> 'CONFIDENTIAL_RECOMMENDATION' OR LEN(Reason) > 0)
);

CREATE INDEX IX_ClassificationDecision_OccurrenceLatest
ON dbo.ClassificationDecision (SourceOccurrenceId, DecidedAtUtc DESC, ClassificationDecisionId DESC);

EXEC(N'
CREATE TRIGGER dbo.TR_ClassificationDecision_AppendOnly
ON dbo.ClassificationDecision
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 51720, ''Classification decisions are immutable.'', 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_ClassificationDecision_RejectRecommendationVisibility
ON dbo.ClassificationDecision
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;

    IF EXISTS
    (
        SELECT 1
        FROM inserted AS decision_row
        JOIN dbo.SourceOccurrence AS occurrence_row
          ON occurrence_row.SourceOccurrenceId = decision_row.SourceOccurrenceId
        JOIN dbo.DocumentVersion AS version_row
          ON version_row.DocumentVersionId = occurrence_row.DocumentVersionId
        JOIN dbo.Document AS document_row
          ON document_row.DocumentId = version_row.DocumentId
        LEFT JOIN dbo.Recommendation AS recommendation_row
          ON recommendation_row.DocumentId = document_row.DocumentId
        WHERE decision_row.Classification = ''APPLICANT_VISIBLE''
          AND (document_row.DocumentType = ''RECOMMENDATION_LETTER''
               OR recommendation_row.RecommendationId IS NOT NULL)
    )
        THROW 51721, ''Recommendation material can never be applicant-visible.'', 1;
END;
');

EXEC(N'
CREATE VIEW dbo.vw_ApplicantVisibleDocumentVersion
AS
    SELECT
        application_row.ApplicationId,
        document_row.DocumentId,
        version_row.DocumentVersionId,
        slot_row.DocumentSlotId,
        slot_row.SlotCode,
        stored_object.StoredObjectId,
        stored_object.ObjectKey,
        stored_object.ByteSize,
        stored_object.MediaType,
        stored_object.PageCount
    FROM dbo.DocumentSlot AS slot_row
    JOIN dbo.Application AS application_row
      ON application_row.ApplicationId = slot_row.ApplicationId
    JOIN dbo.Document AS document_row
      ON document_row.DocumentSlotId = slot_row.DocumentSlotId
    JOIN dbo.DocumentVersion AS version_row
      ON version_row.DocumentVersionId = slot_row.ActiveDocumentVersionId
     AND version_row.DocumentId = document_row.DocumentId
    JOIN dbo.StoredObject AS stored_object
      ON stored_object.StoredObjectId = version_row.StoredObjectId
    WHERE document_row.DocumentType <> ''RECOMMENDATION_LETTER''
      AND NOT EXISTS
      (
          SELECT 1
          FROM dbo.Recommendation AS recommendation_row
          WHERE recommendation_row.DocumentId = document_row.DocumentId
      )
      AND stored_object.ScanResult = ''CLEAN''
      AND EXISTS
      (
          SELECT 1
          FROM dbo.SourceOccurrence AS occurrence_row
          CROSS APPLY
          (
              SELECT TOP (1) decision_row.Classification
              FROM dbo.ClassificationDecision AS decision_row
              WHERE decision_row.SourceOccurrenceId = occurrence_row.SourceOccurrenceId
              ORDER BY decision_row.DecidedAtUtc DESC, decision_row.ClassificationDecisionId DESC
          ) AS latest_decision
          WHERE occurrence_row.DocumentVersionId = version_row.DocumentVersionId
            AND latest_decision.Classification = ''APPLICANT_VISIBLE''
      )
      AND NOT EXISTS
      (
          SELECT 1
          FROM dbo.SourceOccurrence AS occurrence_row
          OUTER APPLY
          (
              SELECT TOP (1) decision_row.Classification
              FROM dbo.ClassificationDecision AS decision_row
              WHERE decision_row.SourceOccurrenceId = occurrence_row.SourceOccurrenceId
              ORDER BY decision_row.DecidedAtUtc DESC, decision_row.ClassificationDecisionId DESC
          ) AS latest_decision
          WHERE occurrence_row.DocumentVersionId = version_row.DocumentVersionId
            AND (latest_decision.Classification IS NULL
                 OR latest_decision.Classification <> ''APPLICANT_VISIBLE'')
      );
');

EXEC(N'
CREATE VIEW dbo.vw_InternalDocumentVersion
AS
    SELECT
        slot_row.ApplicationId,
        document_row.DocumentId,
        document_row.DocumentType,
        version_row.DocumentVersionId,
        version_row.VersionNumber,
        version_row.Classification AS ImportedClassification,
        stored_object.StoredObjectId,
        stored_object.ObjectKey,
        stored_object.KeyVersion,
        stored_object.EnvelopeVersion,
        stored_object.ByteSize,
        stored_object.MediaType,
        stored_object.PageCount,
        stored_object.ScanResult
    FROM dbo.DocumentSlot AS slot_row
    JOIN dbo.Document AS document_row
      ON document_row.DocumentSlotId = slot_row.DocumentSlotId
    JOIN dbo.DocumentVersion AS version_row
      ON version_row.DocumentId = document_row.DocumentId
    JOIN dbo.StoredObject AS stored_object
      ON stored_object.StoredObjectId = version_row.StoredObjectId;
');

EXEC(N'
CREATE PROCEDURE dbo.ValidateApplicationInvitation
    @ApplicationId uniqueidentifier
AS
BEGIN
    SET NOCOUNT ON;

    IF @ApplicationId IS NULL
        THROW 51722, ''An application is required.'', 1;

    IF NOT EXISTS
    (
        SELECT 1
        FROM dbo.ApplicantContact AS contact_row
        JOIN dbo.Application AS application_row
          ON application_row.ApplicantId = contact_row.ApplicantId
        WHERE application_row.ApplicationId = @ApplicationId
          AND contact_row.ContactType = ''REGISTERED_EMAIL''
          AND contact_row.IsPrimary = 1
          AND contact_row.ReviewStatus = ''REVIEWED''
    )
        THROW 51723, ''The registered email is not reviewed.'', 1;

    IF EXISTS
    (
        SELECT 1
        FROM dbo.SourceOccurrence AS occurrence_row
        OUTER APPLY
        (
            SELECT TOP (1) decision_row.Classification
            FROM dbo.ClassificationDecision AS decision_row
            WHERE decision_row.SourceOccurrenceId = occurrence_row.SourceOccurrenceId
            ORDER BY decision_row.DecidedAtUtc DESC, decision_row.ClassificationDecisionId DESC
        ) AS latest_decision
        WHERE occurrence_row.ApplicationId = @ApplicationId
          AND (latest_decision.Classification IS NULL
               OR latest_decision.Classification = ''UNREVIEWED'')
    )
        THROW 51724, ''Every source occurrence must be reviewed before invitation.'', 1;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetInternalApplicationMetrics
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;

    IF @ActorGroup NOT IN
       (N''EHF-Applications-Administrators'', N''EHF-Applications-Trustees'')
        THROW 51725, ''The internal metrics role is not authorized.'', 1;

    SELECT
        CONCAT(applicant.LegalGivenNames, N'' '', applicant.LegalFamilyName) AS ApplicantName,
        JSON_VALUE(section_row.SnapshotJson, ''$.degree'') AS Degree,
        TRY_CONVERT(decimal(8,2), JSON_VALUE(section_row.SnapshotJson, ''$.age_observation'')) AS AgeObservation,
        TRY_CONVERT(decimal(8,2), JSON_VALUE(section_row.SnapshotJson, ''$.academic_age_observation'')) AS AcademicAgeObservation,
        applicant.SelfReportedGender,
        bibliometrics.FirstAuthorPaperCount,
        bibliometrics.LastAuthorPaperCount,
        bibliometrics.TotalPaperCount,
        TRY_CONVERT(int, JSON_VALUE(section_row.SnapshotJson, ''$.h_index'')) AS HIndex,
        TRY_CONVERT(bigint, JSON_VALUE(section_row.SnapshotJson, ''$.total_citations'')) AS TotalCitations,
        JSON_VALUE(section_row.SnapshotJson, ''$.orcid'') AS Orcid,
        bibliometrics.GoogleScholarCitationCount,
        JSON_VALUE(section_row.SnapshotJson, ''$.identity_certainty'') AS IdentityCertainty
    FROM dbo.Application AS application_row
    JOIN dbo.FellowshipCall AS call_row
      ON call_row.FellowshipCallId = application_row.FellowshipCallId
    JOIN dbo.Applicant AS applicant
      ON applicant.ApplicantId = application_row.ApplicantId
    LEFT JOIN dbo.Bibliometrics AS bibliometrics
      ON bibliometrics.ApplicationId = application_row.ApplicationId
    OUTER APPLY
    (
        SELECT TOP (1) version_row.SnapshotJson
        FROM dbo.ApplicationSectionVersion AS version_row
        WHERE version_row.ApplicationId = application_row.ApplicationId
          AND version_row.SectionCode = ''LEGACY_REGISTER_OBSERVATIONS''
        ORDER BY version_row.VersionNumber DESC
    ) AS section_row
    WHERE call_row.CallCode = N''EHF-2026''
    ORDER BY applicant.LegalFamilyName, applicant.LegalGivenNames;
END;
');

GRANT EXECUTE ON dbo.ValidateApplicationInvitation TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetInternalApplicationMetrics TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.DocumentSlot TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.Document TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.StoredObject TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.DocumentVersion TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.Recommendation TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ImportRun TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ImportRow TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.SourceOccurrence TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.CallSourceOccurrence TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ImportException TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ClassificationDecision TO EHFApplicationRuntime;
DENY SELECT ON dbo.vw_ApplicantVisibleDocumentVersion TO EHFApplicationRuntime;
DENY SELECT ON dbo.vw_InternalDocumentVersion TO EHFApplicationRuntime;
