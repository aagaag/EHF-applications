SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE TABLE dbo.ApplicationPublication
(
    ApplicationPublicationId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicationPublication_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    CreatedByImportRunId uniqueidentifier NOT NULL,
    PublicationIdentitySha256 binary(32) NOT NULL,
    ManifestWorkKey varchar(80) NOT NULL,
    Doi varchar(255) NULL,
    HttpLink nvarchar(2048) NULL,
    AuthorsText nvarchar(max) NULL,
    Title nvarchar(2000) NULL,
    JournalText nvarchar(1000) NULL,
    VolumeText nvarchar(255) NULL,
    PagesText nvarchar(255) NULL,
    PublicationYear smallint NULL,
    ResolutionStatus varchar(20) NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicationPublication_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    UpdatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicationPublication_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicationPublication PRIMARY KEY (ApplicationPublicationId),
    CONSTRAINT FK_ApplicationPublication_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT FK_ApplicationPublication_ImportRun FOREIGN KEY (CreatedByImportRunId)
        REFERENCES dbo.ImportRun (ImportRunId),
    CONSTRAINT UQ_ApplicationPublication_Identity UNIQUE
        (ApplicationId, PublicationIdentitySha256),
    CONSTRAINT CK_ApplicationPublication_WorkKey CHECK (LEN(ManifestWorkKey) > 0),
    CONSTRAINT CK_ApplicationPublication_Doi CHECK
        (Doi IS NULL OR (LEN(Doi) > 0 AND Doi COLLATE Latin1_General_100_BIN2 = LOWER(Doi) COLLATE Latin1_General_100_BIN2 AND Doi NOT LIKE 'doi:%' AND Doi NOT LIKE 'https://doi.org/%')),
    CONSTRAINT CK_ApplicationPublication_Link CHECK
        (HttpLink IS NULL OR HttpLink LIKE N'http://%' OR HttpLink LIKE N'https://%'),
    CONSTRAINT CK_ApplicationPublication_Year CHECK
        (PublicationYear IS NULL OR PublicationYear BETWEEN 1600 AND 2200),
    CONSTRAINT CK_ApplicationPublication_Status CHECK
        (ResolutionStatus IN ('RESOLVED', 'AMBIGUOUS', 'UNRESOLVED'))
);

CREATE UNIQUE INDEX UX_ApplicationPublication_Doi
ON dbo.ApplicationPublication (ApplicationId, Doi)
WHERE Doi IS NOT NULL;

CREATE INDEX IX_ApplicationPublication_Application
ON dbo.ApplicationPublication (ApplicationId, PublicationYear, ApplicationPublicationId);

CREATE TABLE dbo.ApplicationPublicationSourceOccurrence
(
    ApplicationPublicationSourceOccurrenceId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicationPublicationSourceOccurrence_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationPublicationId uniqueidentifier NOT NULL,
    ImportRunId uniqueidentifier NOT NULL,
    SourceType varchar(20) NOT NULL,
    SourceLocatorSha256 binary(32) NOT NULL,
    SourcePage int NULL,
    RawCitation nvarchar(max) NOT NULL,
    PayloadSha256 binary(32) NOT NULL,
    RecordedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicationPublicationSourceOccurrence_RecordedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ApplicationPublicationSourceOccurrence PRIMARY KEY
        (ApplicationPublicationSourceOccurrenceId),
    CONSTRAINT FK_ApplicationPublicationSourceOccurrence_Publication FOREIGN KEY
        (ApplicationPublicationId) REFERENCES dbo.ApplicationPublication (ApplicationPublicationId),
    CONSTRAINT FK_ApplicationPublicationSourceOccurrence_Run FOREIGN KEY (ImportRunId)
        REFERENCES dbo.ImportRun (ImportRunId),
    CONSTRAINT UQ_ApplicationPublicationSourceOccurrence_Payload UNIQUE
        (ApplicationPublicationId, SourceLocatorSha256, PayloadSha256),
    CONSTRAINT CK_ApplicationPublicationSourceOccurrence_Type CHECK
        (SourceType IN ('WORKBOOK', 'DOSSIER')),
    CONSTRAINT CK_ApplicationPublicationSourceOccurrence_Page CHECK
        (SourcePage IS NULL OR SourcePage > 0),
    CONSTRAINT CK_ApplicationPublicationSourceOccurrence_Citation CHECK
        (LEN(RawCitation) > 0)
);

CREATE TABLE dbo.PublicationMetadataObservation
(
    PublicationMetadataObservationId uniqueidentifier NOT NULL
        CONSTRAINT DF_PublicationMetadataObservation_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationPublicationId uniqueidentifier NOT NULL,
    ImportRunId uniqueidentifier NOT NULL,
    SourceCode varchar(30) NOT NULL,
    SourceIdentifier nvarchar(2048) NULL,
    MetadataJson nvarchar(max) NOT NULL,
    ObservedAtUtc datetime2(7) NULL,
    PayloadSha256 binary(32) NOT NULL,
    RecordedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_PublicationMetadataObservation_RecordedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_PublicationMetadataObservation PRIMARY KEY
        (PublicationMetadataObservationId),
    CONSTRAINT FK_PublicationMetadataObservation_Publication FOREIGN KEY
        (ApplicationPublicationId) REFERENCES dbo.ApplicationPublication (ApplicationPublicationId),
    CONSTRAINT FK_PublicationMetadataObservation_Run FOREIGN KEY (ImportRunId)
        REFERENCES dbo.ImportRun (ImportRunId),
    CONSTRAINT UQ_PublicationMetadataObservation_Payload UNIQUE
        (ApplicationPublicationId, SourceCode, PayloadSha256),
    CONSTRAINT CK_PublicationMetadataObservation_Source CHECK
        (SourceCode IN ('CROSSREF', 'BIORXIV', 'MEDRXIV', 'WORKBOOK', 'DOSSIER')),
    CONSTRAINT CK_PublicationMetadataObservation_Json CHECK (ISJSON(MetadataJson) = 1)
);

CREATE TABLE dbo.PublicationCitationObservation
(
    PublicationCitationObservationId uniqueidentifier NOT NULL
        CONSTRAINT DF_PublicationCitationObservation_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationPublicationId uniqueidentifier NOT NULL,
    ImportRunId uniqueidentifier NOT NULL,
    SourceCode varchar(30) NOT NULL,
    CitationCount bigint NULL,
    CitationStatus varchar(40) NOT NULL,
    EvidenceJson nvarchar(max) NULL,
    ObservedAtUtc datetime2(7) NULL,
    PayloadSha256 binary(32) NOT NULL,
    RecordedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_PublicationCitationObservation_RecordedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_PublicationCitationObservation PRIMARY KEY
        (PublicationCitationObservationId),
    CONSTRAINT FK_PublicationCitationObservation_Publication FOREIGN KEY
        (ApplicationPublicationId) REFERENCES dbo.ApplicationPublication (ApplicationPublicationId),
    CONSTRAINT FK_PublicationCitationObservation_Run FOREIGN KEY (ImportRunId)
        REFERENCES dbo.ImportRun (ImportRunId),
    CONSTRAINT UQ_PublicationCitationObservation_Payload UNIQUE
        (ApplicationPublicationId, SourceCode, PayloadSha256),
    CONSTRAINT CK_PublicationCitationObservation_Source CHECK
        (SourceCode IN ('GOOGLE_SCHOLAR', 'BIORXIV', 'MEDRXIV')),
    CONSTRAINT CK_PublicationCitationObservation_Status CHECK
        (CitationStatus IN ('OBSERVED', 'MANUAL_REQUIRED', 'NOT_AVAILABLE_FROM_SOURCE', 'NOT_FOUND', 'NOT_APPLICABLE')),
    CONSTRAINT CK_PublicationCitationObservation_Count CHECK
        (CitationCount IS NULL OR CitationCount >= 0),
    CONSTRAINT CK_PublicationCitationObservation_StatusCount CHECK
        ((CitationStatus = 'OBSERVED' AND CitationCount IS NOT NULL)
         OR (CitationStatus <> 'OBSERVED' AND CitationCount IS NULL)),
    CONSTRAINT CK_PublicationCitationObservation_Evidence CHECK
        (EvidenceJson IS NULL OR ISJSON(EvidenceJson) = 1)
);

EXEC(N'
CREATE TRIGGER dbo.TR_ApplicationPublication_NoOverwrite
ON dbo.ApplicationPublication
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM deleted) AND NOT EXISTS (SELECT 1 FROM inserted)
        THROW 54020, ''Application publications cannot be deleted.'', 1;
    IF EXISTS
    (
        SELECT 1
        FROM deleted AS old_row
        JOIN inserted AS new_row
          ON new_row.ApplicationPublicationId = old_row.ApplicationPublicationId
        WHERE new_row.ApplicationId <> old_row.ApplicationId
           OR new_row.CreatedByImportRunId <> old_row.CreatedByImportRunId
           OR new_row.PublicationIdentitySha256 <> old_row.PublicationIdentitySha256
           OR new_row.ManifestWorkKey <> old_row.ManifestWorkKey
           OR new_row.ResolutionStatus <> old_row.ResolutionStatus
           OR (old_row.Doi IS NOT NULL AND (new_row.Doi IS NULL OR new_row.Doi <> old_row.Doi))
           OR (old_row.HttpLink IS NOT NULL AND (new_row.HttpLink IS NULL OR new_row.HttpLink <> old_row.HttpLink))
           OR (old_row.AuthorsText IS NOT NULL AND (new_row.AuthorsText IS NULL OR new_row.AuthorsText <> old_row.AuthorsText))
           OR (old_row.Title IS NOT NULL AND (new_row.Title IS NULL OR new_row.Title <> old_row.Title))
           OR (old_row.JournalText IS NOT NULL AND (new_row.JournalText IS NULL OR new_row.JournalText <> old_row.JournalText))
           OR (old_row.VolumeText IS NOT NULL AND (new_row.VolumeText IS NULL OR new_row.VolumeText <> old_row.VolumeText))
           OR (old_row.PagesText IS NOT NULL AND (new_row.PagesText IS NULL OR new_row.PagesText <> old_row.PagesText))
           OR (old_row.PublicationYear IS NOT NULL AND (new_row.PublicationYear IS NULL OR new_row.PublicationYear <> old_row.PublicationYear))
    )
        THROW 54021, ''A non-blank publication value cannot be overwritten or cleared.'', 1;
    UPDATE target_row
       SET Doi = COALESCE(target_row.Doi, new_row.Doi),
           HttpLink = COALESCE(target_row.HttpLink, new_row.HttpLink),
           AuthorsText = COALESCE(target_row.AuthorsText, new_row.AuthorsText),
           Title = COALESCE(target_row.Title, new_row.Title),
           JournalText = COALESCE(target_row.JournalText, new_row.JournalText),
           VolumeText = COALESCE(target_row.VolumeText, new_row.VolumeText),
           PagesText = COALESCE(target_row.PagesText, new_row.PagesText),
           PublicationYear = COALESCE(target_row.PublicationYear, new_row.PublicationYear),
           UpdatedAtUtc = SYSUTCDATETIME()
    FROM dbo.ApplicationPublication AS target_row
    JOIN inserted AS new_row
      ON new_row.ApplicationPublicationId = target_row.ApplicationPublicationId;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_ApplicationPublicationSourceOccurrence_AppendOnly
ON dbo.ApplicationPublicationSourceOccurrence
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 54022, ''Application publication source occurrences are immutable.'', 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_PublicationMetadataObservation_AppendOnly
ON dbo.PublicationMetadataObservation
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 54023, ''Publication metadata observations are immutable.'', 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_PublicationCitationObservation_AppendOnly
ON dbo.PublicationCitationObservation
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 54024, ''Publication citation observations are immutable.'', 1;
END;
');

DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicationPublication TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicationPublicationSourceOccurrence TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.PublicationMetadataObservation TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.PublicationCitationObservation TO EHFApplicationRuntime;
