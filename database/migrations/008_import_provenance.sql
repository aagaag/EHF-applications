SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE TABLE dbo.ImportRun
(
    ImportRunId uniqueidentifier NOT NULL
        CONSTRAINT DF_ImportRun_Id DEFAULT NEWSEQUENTIALID(),
    FellowshipCallId uniqueidentifier NOT NULL,
    ImportFingerprintSha256 binary(32) NOT NULL,
    ImporterVersion varchar(80) NOT NULL,
    RunStatus varchar(20) NOT NULL,
    StartedByIdentity nvarchar(255) NOT NULL,
    StartedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ImportRun_StartedAtUtc DEFAULT SYSUTCDATETIME(),
    CompletedAtUtc datetime2(7) NULL,
    CONSTRAINT PK_ImportRun PRIMARY KEY (ImportRunId),
    CONSTRAINT FK_ImportRun_Call FOREIGN KEY (FellowshipCallId)
        REFERENCES dbo.FellowshipCall (FellowshipCallId),
    CONSTRAINT CK_ImportRun_Version CHECK (LEN(ImporterVersion) > 0),
    CONSTRAINT CK_ImportRun_Status CHECK (RunStatus IN ('PLANNED', 'RUNNING', 'COMPLETED', 'FAILED')),
    CONSTRAINT CK_ImportRun_Actor CHECK (LEN(StartedByIdentity) > 0),
    CONSTRAINT CK_ImportRun_Completion CHECK
        ((RunStatus = 'COMPLETED' AND CompletedAtUtc IS NOT NULL)
         OR (RunStatus <> 'COMPLETED' AND CompletedAtUtc IS NULL))
);

CREATE INDEX IX_ImportRun_Fingerprint
ON dbo.ImportRun (FellowshipCallId, ImportFingerprintSha256, RunStatus);

CREATE TABLE dbo.ImportRow
(
    ImportRowId uniqueidentifier NOT NULL
        CONSTRAINT DF_ImportRow_Id DEFAULT NEWSEQUENTIALID(),
    ImportRunId uniqueidentifier NOT NULL,
    SourceRowNumber int NOT NULL,
    ApplicationId uniqueidentifier NULL,
    SourceRowSha256 binary(32) NOT NULL,
    MatchStatus varchar(20) NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ImportRow_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ImportRow PRIMARY KEY (ImportRowId),
    CONSTRAINT FK_ImportRow_Run FOREIGN KEY (ImportRunId)
        REFERENCES dbo.ImportRun (ImportRunId),
    CONSTRAINT FK_ImportRow_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT UQ_ImportRow_Source UNIQUE (ImportRunId, SourceRowNumber),
    CONSTRAINT CK_ImportRow_Number CHECK (SourceRowNumber > 0),
    CONSTRAINT CK_ImportRow_MatchStatus CHECK
        (MatchStatus IN ('MATCHED', 'UNMATCHED', 'AMBIGUOUS', 'DUPLICATE'))
);

CREATE TABLE dbo.SourceOccurrence
(
    SourceOccurrenceId uniqueidentifier NOT NULL
        CONSTRAINT DF_SourceOccurrence_Id DEFAULT NEWSEQUENTIALID(),
    ImportRunId uniqueidentifier NOT NULL,
    ImportRowId uniqueidentifier NULL,
    ApplicationId uniqueidentifier NOT NULL,
    DocumentVersionId uniqueidentifier NULL,
    SourceLocatorSha256 binary(32) NOT NULL,
    SourceContentSha256 binary(32) NOT NULL,
    SourceByteSize bigint NOT NULL,
    SourceMediaType varchar(100) NULL,
    ImportDisposition varchar(20) NOT NULL,
    ObservedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_SourceOccurrence_ObservedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_SourceOccurrence PRIMARY KEY (SourceOccurrenceId),
    CONSTRAINT FK_SourceOccurrence_Run FOREIGN KEY (ImportRunId)
        REFERENCES dbo.ImportRun (ImportRunId),
    CONSTRAINT FK_SourceOccurrence_Row FOREIGN KEY (ImportRowId)
        REFERENCES dbo.ImportRow (ImportRowId),
    CONSTRAINT FK_SourceOccurrence_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT FK_SourceOccurrence_DocumentVersion FOREIGN KEY (DocumentVersionId)
        REFERENCES dbo.DocumentVersion (DocumentVersionId),
    CONSTRAINT UQ_SourceOccurrence_Locator UNIQUE (ImportRunId, SourceLocatorSha256),
    CONSTRAINT CK_SourceOccurrence_Size CHECK (SourceByteSize >= 0),
    CONSTRAINT CK_SourceOccurrence_Disposition CHECK
        (ImportDisposition IN ('INGESTED', 'QUARANTINED', 'REJECTED', 'NON_PDF')),
    CONSTRAINT CK_SourceOccurrence_IngestedVersion CHECK
        ((ImportDisposition = 'INGESTED' AND DocumentVersionId IS NOT NULL)
         OR (ImportDisposition <> 'INGESTED' AND DocumentVersionId IS NULL))
);

CREATE TABLE dbo.CallSourceOccurrence
(
    CallSourceOccurrenceId uniqueidentifier NOT NULL
        CONSTRAINT DF_CallSourceOccurrence_Id DEFAULT NEWSEQUENTIALID(),
    ImportRunId uniqueidentifier NOT NULL,
    SourceLocatorSha256 binary(32) NOT NULL,
    SourceContentSha256 binary(32) NOT NULL,
    SourceByteSize bigint NOT NULL,
    SourceMediaType varchar(100) NULL,
    ImportDisposition varchar(40) NOT NULL,
    ObservedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_CallSourceOccurrence_ObservedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_CallSourceOccurrence PRIMARY KEY (CallSourceOccurrenceId),
    CONSTRAINT FK_CallSourceOccurrence_Run FOREIGN KEY (ImportRunId)
        REFERENCES dbo.ImportRun (ImportRunId),
    CONSTRAINT UQ_CallSourceOccurrence_Locator UNIQUE (ImportRunId, SourceLocatorSha256),
    CONSTRAINT CK_CallSourceOccurrence_Size CHECK (SourceByteSize >= 0),
    CONSTRAINT CK_CallSourceOccurrence_Disposition CHECK
        (ImportDisposition = 'REVIEWED_INTERNAL_EXCLUSION')
);

CREATE INDEX IX_SourceOccurrence_Application
ON dbo.SourceOccurrence (ApplicationId, SourceOccurrenceId);

EXEC(N'
CREATE TRIGGER dbo.TR_SourceOccurrence_DocumentVersionApplicationMatches
ON dbo.SourceOccurrence
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;

    IF EXISTS
    (
        SELECT 1
        FROM inserted AS occurrence_row
        JOIN dbo.DocumentVersion AS version_row
          ON version_row.DocumentVersionId = occurrence_row.DocumentVersionId
        JOIN dbo.Document AS document_row
          ON document_row.DocumentId = version_row.DocumentId
        JOIN dbo.DocumentSlot AS slot_row
          ON slot_row.DocumentSlotId = document_row.DocumentSlotId
        WHERE occurrence_row.ApplicationId <> slot_row.ApplicationId
    )
        THROW 51712, ''A source occurrence must use a document version owned by its application.'', 1;
END;
');

CREATE TABLE dbo.ImportException
(
    ImportExceptionId uniqueidentifier NOT NULL
        CONSTRAINT DF_ImportException_Id DEFAULT NEWSEQUENTIALID(),
    ImportRunId uniqueidentifier NOT NULL,
    ImportRowId uniqueidentifier NULL,
    SourceOccurrenceId uniqueidentifier NULL,
    ExceptionCode varchar(80) NOT NULL,
    DetailSha256 binary(32) NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ImportException_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ImportException PRIMARY KEY (ImportExceptionId),
    CONSTRAINT FK_ImportException_Run FOREIGN KEY (ImportRunId)
        REFERENCES dbo.ImportRun (ImportRunId),
    CONSTRAINT FK_ImportException_Row FOREIGN KEY (ImportRowId)
        REFERENCES dbo.ImportRow (ImportRowId),
    CONSTRAINT FK_ImportException_Occurrence FOREIGN KEY (SourceOccurrenceId)
        REFERENCES dbo.SourceOccurrence (SourceOccurrenceId),
    CONSTRAINT CK_ImportException_Code CHECK (LEN(ExceptionCode) > 0)
);

EXEC(N'
CREATE TRIGGER dbo.TR_SourceOccurrence_AppendOnly
ON dbo.SourceOccurrence
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 51710, ''Source occurrences are immutable.'', 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_ImportRow_AppendOnly
ON dbo.ImportRow
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 51711, ''Import rows are immutable.'', 1;
END;
');
