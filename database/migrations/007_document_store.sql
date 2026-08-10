SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE TABLE dbo.DocumentSlot
(
    DocumentSlotId uniqueidentifier NOT NULL
        CONSTRAINT DF_DocumentSlot_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    SlotCode varchar(80) NOT NULL,
    CreatedByIdentity nvarchar(255) NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_DocumentSlot_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_DocumentSlot PRIMARY KEY (DocumentSlotId),
    CONSTRAINT FK_DocumentSlot_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT UQ_DocumentSlot_ApplicationCode UNIQUE (ApplicationId, SlotCode),
    CONSTRAINT CK_DocumentSlot_Code CHECK (LEN(SlotCode) > 0),
    CONSTRAINT CK_DocumentSlot_Actor CHECK (LEN(CreatedByIdentity) > 0)
);

CREATE TABLE dbo.Document
(
    DocumentId uniqueidentifier NOT NULL
        CONSTRAINT DF_Document_Id DEFAULT NEWSEQUENTIALID(),
    DocumentSlotId uniqueidentifier NOT NULL,
    DocumentType varchar(40) NOT NULL,
    CreatedByIdentity nvarchar(255) NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_Document_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Document PRIMARY KEY (DocumentId),
    CONSTRAINT FK_Document_Slot FOREIGN KEY (DocumentSlotId)
        REFERENCES dbo.DocumentSlot (DocumentSlotId),
    CONSTRAINT UQ_Document_Slot UNIQUE (DocumentSlotId),
    CONSTRAINT CK_Document_Type CHECK (DocumentType IN
        ('CV', 'COVER_LETTER', 'RESEARCH_PLAN', 'PUBLICATION_LIST',
         'RECOMMENDATION_LETTER', 'OTHER')),
    CONSTRAINT CK_Document_Actor CHECK (LEN(CreatedByIdentity) > 0)
);

CREATE TABLE dbo.StoredObject
(
    StoredObjectId uniqueidentifier NOT NULL
        CONSTRAINT DF_StoredObject_Id DEFAULT NEWSEQUENTIALID(),
    ObjectKey varchar(32) NOT NULL,
    KeyVersion smallint NOT NULL,
    EnvelopeVersion tinyint NOT NULL,
    AesGcmNonce binary(12) NOT NULL,
    PlaintextSha256 binary(32) NOT NULL,
    CiphertextSha256 binary(32) NOT NULL,
    ByteSize bigint NOT NULL,
    MediaType varchar(100) NOT NULL,
    PageCount int NOT NULL,
    ScanEngine varchar(100) NOT NULL,
    ScanSignature nvarchar(200) NULL,
    ScannedAtUtc datetime2(7) NOT NULL,
    ScanResult varchar(20) NOT NULL,
    CreatedByIdentity nvarchar(255) NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_StoredObject_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_StoredObject PRIMARY KEY (StoredObjectId),
    CONSTRAINT UQ_StoredObject_Key UNIQUE (ObjectKey),
    CONSTRAINT CK_StoredObject_Key CHECK
        (LEN(ObjectKey) = 32 AND ObjectKey NOT LIKE '%[^0-9a-f]%'),
    CONSTRAINT CK_StoredObject_KeyVersion CHECK (KeyVersion > 0),
    CONSTRAINT CK_StoredObject_EnvelopeVersion CHECK (EnvelopeVersion > 0),
    CONSTRAINT CK_StoredObject_Size CHECK (ByteSize > 0),
    CONSTRAINT CK_StoredObject_MediaType CHECK (MediaType = 'application/pdf'),
    CONSTRAINT CK_StoredObject_PageCount CHECK (PageCount > 0),
    CONSTRAINT CK_StoredObject_ScanEngine CHECK (LEN(ScanEngine) > 0),
    CONSTRAINT CK_StoredObject_ScanResult CHECK
        (ScanResult IN ('CLEAN', 'INFECTED', 'UNAVAILABLE', 'ERROR')),
    CONSTRAINT CK_StoredObject_Actor CHECK (LEN(CreatedByIdentity) > 0)
);

CREATE TABLE dbo.DocumentVersion
(
    DocumentVersionId uniqueidentifier NOT NULL
        CONSTRAINT DF_DocumentVersion_Id DEFAULT NEWSEQUENTIALID(),
    DocumentId uniqueidentifier NOT NULL,
    StoredObjectId uniqueidentifier NOT NULL,
    VersionNumber int NOT NULL,
    Classification varchar(40) NOT NULL
        CONSTRAINT DF_DocumentVersion_Classification DEFAULT 'UNREVIEWED',
    CreatedByIdentity nvarchar(255) NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_DocumentVersion_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_DocumentVersion PRIMARY KEY (DocumentVersionId),
    CONSTRAINT FK_DocumentVersion_Document FOREIGN KEY (DocumentId)
        REFERENCES dbo.Document (DocumentId),
    CONSTRAINT FK_DocumentVersion_StoredObject FOREIGN KEY (StoredObjectId)
        REFERENCES dbo.StoredObject (StoredObjectId),
    CONSTRAINT UQ_DocumentVersion_Number UNIQUE (DocumentId, VersionNumber),
    CONSTRAINT UQ_DocumentVersion_StoredObject UNIQUE (StoredObjectId),
    CONSTRAINT CK_DocumentVersion_Number CHECK (VersionNumber > 0),
    CONSTRAINT CK_DocumentVersion_Classification CHECK (Classification IN
        ('UNREVIEWED', 'APPLICANT_VISIBLE', 'CONFIDENTIAL_RECOMMENDATION',
         'INTERNAL_ADMINISTRATIVE')),
    CONSTRAINT CK_DocumentVersion_Actor CHECK (LEN(CreatedByIdentity) > 0)
);

ALTER TABLE dbo.DocumentSlot
    ADD ActiveDocumentVersionId uniqueidentifier NULL;

ALTER TABLE dbo.DocumentSlot
    ADD CONSTRAINT FK_DocumentSlot_ActiveVersion FOREIGN KEY (ActiveDocumentVersionId)
        REFERENCES dbo.DocumentVersion (DocumentVersionId);

CREATE TABLE dbo.Recommendation
(
    RecommendationId uniqueidentifier NOT NULL
        CONSTRAINT DF_Recommendation_Id DEFAULT NEWSEQUENTIALID(),
    DocumentId uniqueidentifier NOT NULL,
    ArrivalChannel varchar(30) NOT NULL,
    CreatedByIdentity nvarchar(255) NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_Recommendation_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Recommendation PRIMARY KEY (RecommendationId),
    CONSTRAINT FK_Recommendation_Document FOREIGN KEY (DocumentId)
        REFERENCES dbo.Document (DocumentId),
    CONSTRAINT UQ_Recommendation_Document UNIQUE (DocumentId),
    CONSTRAINT CK_Recommendation_ArrivalChannel CHECK
        (ArrivalChannel IN ('DIRECT_REFEREE', 'APPLICANT_FORWARDED', 'UNKNOWN_LEGACY')),
    CONSTRAINT CK_Recommendation_Actor CHECK (LEN(CreatedByIdentity) > 0)
);

EXEC(N'
CREATE TRIGGER dbo.TR_Document_AppendOnly
ON dbo.Document
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 51703, ''Documents are immutable.'', 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_Recommendation_AppendOnly
ON dbo.Recommendation
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 51704, ''Recommendation links are immutable.'', 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_Recommendation_RequiresRecommendationDocumentType
ON dbo.Recommendation
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;

    IF EXISTS
    (
        SELECT 1
        FROM inserted AS recommendation_row
        JOIN dbo.Document AS document_row
          ON document_row.DocumentId = recommendation_row.DocumentId
        WHERE document_row.DocumentType <> ''RECOMMENDATION_LETTER''
    )
        THROW 51705, ''A recommendation link requires a recommendation-letter document type.'', 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_DocumentSlot_ActiveVersionBelongsToSlot
ON dbo.DocumentSlot
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    IF EXISTS
    (
        SELECT 1
        FROM inserted AS slot_row
        JOIN dbo.DocumentVersion AS version_row
          ON version_row.DocumentVersionId = slot_row.ActiveDocumentVersionId
        JOIN dbo.Document AS document_row
          ON document_row.DocumentId = version_row.DocumentId
        WHERE document_row.DocumentSlotId <> slot_row.DocumentSlotId
    )
        THROW 51700, ''An active version must belong to its document slot.'', 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_StoredObject_AppendOnly
ON dbo.StoredObject
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 51701, ''Stored objects are immutable.'', 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_DocumentVersion_AppendOnly
ON dbo.DocumentVersion
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 51702, ''Document versions are immutable.'', 1;
END;
');
