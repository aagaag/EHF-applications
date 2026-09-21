SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE TABLE dbo.InternalReviewArtifactProvenance
(
    InternalReviewArtifactProvenanceId uniqueidentifier NOT NULL
        CONSTRAINT DF_InternalReviewArtifactProvenance_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    Category varchar(20) NOT NULL,
    ArtifactDocumentVersionId uniqueidentifier NOT NULL,
    SourceDocumentVersionId uniqueidentifier NOT NULL,
    SegmentOrder int NOT NULL,
    FirstPage int NOT NULL,
    LastPage int NOT NULL,
    SourcePlaintextSha256 binary(32) NOT NULL,
    ReviewedByIdentity nvarchar(255) NOT NULL,
    ReviewedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_InternalReviewArtifactProvenance_ReviewedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_InternalReviewArtifactProvenance PRIMARY KEY
        (InternalReviewArtifactProvenanceId),
    CONSTRAINT FK_InternalReviewArtifactProvenance_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT FK_InternalReviewArtifactProvenance_ArtifactVersion FOREIGN KEY
        (ArtifactDocumentVersionId) REFERENCES dbo.DocumentVersion (DocumentVersionId),
    CONSTRAINT FK_InternalReviewArtifactProvenance_SourceVersion FOREIGN KEY
        (SourceDocumentVersionId) REFERENCES dbo.DocumentVersion (DocumentVersionId),
    CONSTRAINT UQ_InternalReviewArtifactProvenance_Segment UNIQUE
        (ArtifactDocumentVersionId, SegmentOrder),
    CONSTRAINT CK_InternalReviewArtifactProvenance_Category CHECK
        (Category IN ('APPLICATION', 'CURRICULUM', 'PUBLICATIONS')),
    CONSTRAINT CK_InternalReviewArtifactProvenance_SegmentOrder CHECK (SegmentOrder > 0),
    CONSTRAINT CK_InternalReviewArtifactProvenance_PageRange CHECK
        (FirstPage > 0 AND LastPage >= FirstPage),
    CONSTRAINT CK_InternalReviewArtifactProvenance_Reviewer CHECK
        (LEN(ReviewedByIdentity) > 0)
);

EXEC(N'
CREATE TRIGGER dbo.TR_InternalReviewArtifactProvenance_AppendOnly
ON dbo.InternalReviewArtifactProvenance
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 54120, ''Internal review artifact provenance is immutable.'', 1;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ListInternalReviewArtifacts
    @ApplicationId uniqueidentifier,
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    IF @ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')
       OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
        THROW 54110, ''Administrator or trustee authorization is required.'', 1;

    SELECT provenance_row.Category, version_row.DocumentVersionId
    FROM dbo.InternalReviewArtifactProvenance AS provenance_row
    JOIN dbo.DocumentVersion AS version_row
      ON version_row.DocumentVersionId = provenance_row.ArtifactDocumentVersionId
    JOIN dbo.Document AS document_row
      ON document_row.DocumentId = version_row.DocumentId
    JOIN dbo.DocumentSlot AS slot_row
      ON slot_row.DocumentSlotId = document_row.DocumentSlotId
     AND slot_row.ActiveDocumentVersionId = version_row.DocumentVersionId
    JOIN dbo.StoredObject AS object_row
      ON object_row.StoredObjectId = version_row.StoredObjectId
    WHERE provenance_row.ApplicationId = @ApplicationId
      AND slot_row.ApplicationId = @ApplicationId
      AND slot_row.ApplicantVisible = 0
      AND slot_row.SlotCode = CASE provenance_row.Category
          WHEN ''APPLICATION'' THEN ''REVIEW-ARTIFACT-APPLICATION''
          WHEN ''CURRICULUM'' THEN ''REVIEW-ARTIFACT-CURRICULUM''
          WHEN ''PUBLICATIONS'' THEN ''REVIEW-ARTIFACT-PUBLICATIONS'' END
      AND document_row.DocumentType = CASE provenance_row.Category
          WHEN ''APPLICATION'' THEN ''RESEARCH_PLAN''
          WHEN ''CURRICULUM'' THEN ''CV''
          WHEN ''PUBLICATIONS'' THEN ''PUBLICATION_LIST'' END
      AND version_row.Classification = ''INTERNAL_ADMINISTRATIVE''
      AND document_row.DocumentType <> ''RECOMMENDATION_LETTER''
      AND object_row.ScanResult = ''CLEAN''
      AND NOT EXISTS
          (SELECT 1 FROM dbo.Recommendation AS recommendation_row
           WHERE recommendation_row.DocumentId = document_row.DocumentId)
    GROUP BY provenance_row.Category, version_row.DocumentVersionId
    ORDER BY provenance_row.Category;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetInternalReviewArtifact
    @ApplicationId uniqueidentifier,
    @Category varchar(20),
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    IF @ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')
       OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
       OR @Category NOT IN (''APPLICATION'', ''CURRICULUM'', ''PUBLICATIONS'')
        THROW 54110, ''Administrator or trustee authorization is required.'', 1;

    DECLARE @DocumentVersionId uniqueidentifier;
    SELECT TOP (1) @DocumentVersionId = version_row.DocumentVersionId
    FROM dbo.InternalReviewArtifactProvenance AS provenance_row
    JOIN dbo.DocumentVersion AS version_row
      ON version_row.DocumentVersionId = provenance_row.ArtifactDocumentVersionId
    JOIN dbo.Document AS document_row
      ON document_row.DocumentId = version_row.DocumentId
    JOIN dbo.DocumentSlot AS slot_row
      ON slot_row.DocumentSlotId = document_row.DocumentSlotId
     AND slot_row.ActiveDocumentVersionId = version_row.DocumentVersionId
    JOIN dbo.StoredObject AS object_row
      ON object_row.StoredObjectId = version_row.StoredObjectId
    WHERE provenance_row.ApplicationId = @ApplicationId
      AND provenance_row.Category = @Category
      AND slot_row.ApplicationId = @ApplicationId
      AND slot_row.ApplicantVisible = 0
      AND slot_row.SlotCode = CASE provenance_row.Category
          WHEN ''APPLICATION'' THEN ''REVIEW-ARTIFACT-APPLICATION''
          WHEN ''CURRICULUM'' THEN ''REVIEW-ARTIFACT-CURRICULUM''
          WHEN ''PUBLICATIONS'' THEN ''REVIEW-ARTIFACT-PUBLICATIONS'' END
      AND document_row.DocumentType = CASE provenance_row.Category
          WHEN ''APPLICATION'' THEN ''RESEARCH_PLAN''
          WHEN ''CURRICULUM'' THEN ''CV''
          WHEN ''PUBLICATIONS'' THEN ''PUBLICATION_LIST'' END
      AND version_row.Classification = ''INTERNAL_ADMINISTRATIVE''
      AND document_row.DocumentType <> ''RECOMMENDATION_LETTER''
      AND object_row.ScanResult = ''CLEAN''
      AND NOT EXISTS
          (SELECT 1 FROM dbo.Recommendation AS recommendation_row
           WHERE recommendation_row.DocumentId = document_row.DocumentId)
    ORDER BY version_row.CreatedAtUtc DESC, version_row.DocumentVersionId DESC;

    IF @DocumentVersionId IS NOT NULL
        INSERT dbo.AuditEvent
            (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
        VALUES
            (@ApplicationId, ''INTERNAL_DOCUMENT_ACCESS_REQUESTED'',
             LTRIM(RTRIM(@ActorIdentity)), ''DocumentVersion'', @DocumentVersionId,
             (SELECT @ActorGroup AS actorGroup, ''VIEW'' AS purpose,
                     @Category AS category FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));

    SELECT slot_row.ApplicationId, document_row.DocumentId,
           version_row.DocumentVersionId, object_row.StoredObjectId,
           object_row.ObjectKey, object_row.KeyVersion, object_row.EnvelopeVersion,
           object_row.AesGcmNonce, object_row.PlaintextSha256,
           object_row.CiphertextSha256, object_row.ByteSize
    FROM dbo.DocumentVersion AS version_row
    JOIN dbo.Document AS document_row ON document_row.DocumentId = version_row.DocumentId
    JOIN dbo.DocumentSlot AS slot_row ON slot_row.DocumentSlotId = document_row.DocumentSlotId
    JOIN dbo.StoredObject AS object_row ON object_row.StoredObjectId = version_row.StoredObjectId
    WHERE version_row.DocumentVersionId = @DocumentVersionId
      AND slot_row.ActiveDocumentVersionId = version_row.DocumentVersionId;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.RecordInternalReviewArtifactFailure
    @ApplicationId uniqueidentifier,
    @Category varchar(20),
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    IF @ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')
       OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
       OR @Category NOT IN (''APPLICATION'', ''CURRICULUM'', ''PUBLICATIONS'', ''INVALID'')
        THROW 54110, ''Administrator or trustee authorization is required.'', 1;

    IF EXISTS (SELECT 1 FROM dbo.Application WHERE ApplicationId=@ApplicationId)
    BEGIN
        INSERT dbo.AuditEvent
            (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
        SELECT @ApplicationId, event_row.EventType, LTRIM(RTRIM(@ActorIdentity)),
               ''Application'', @ApplicationId,
               (SELECT @ActorGroup AS actorGroup, ''VIEW'' AS purpose,
                       @Category AS category FOR JSON PATH, WITHOUT_ARRAY_WRAPPER)
        FROM (VALUES (''INTERNAL_DOCUMENT_ACCESS_REQUESTED''),
                     (''INTERNAL_DOCUMENT_ACCESS_FAILED'')) AS event_row(EventType);
    END;
END;
');

GRANT EXECUTE ON dbo.ListInternalReviewArtifacts TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetInternalReviewArtifact TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.RecordInternalReviewArtifactFailure TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.InternalReviewArtifactProvenance TO EHFApplicationRuntime;
