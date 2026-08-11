SET NOCOUNT ON;
SET XACT_ABORT ON;

EXEC(N'
ALTER TABLE dbo.DocumentSlot
ADD ApplicantUploadMode varchar(12) NOT NULL
        CONSTRAINT DF_DocumentSlot_ApplicantUploadMode DEFAULT ''CLOSED'',
    ApplicantVisible bit NOT NULL
        CONSTRAINT DF_DocumentSlot_ApplicantVisible DEFAULT 0,
    SlotLabel nvarchar(200) NULL,
    RequiredForCompletion bit NOT NULL
        CONSTRAINT DF_DocumentSlot_RequiredForCompletion DEFAULT 0,
    UploadReason nvarchar(1000) NULL,
    OpenedByIdentity nvarchar(255) NULL,
    OpenedAtUtc datetime2(7) NULL,
    RowVersion rowversion NOT NULL;
');

EXEC(N'
UPDATE dbo.DocumentSlot SET SlotLabel = CONVERT(nvarchar(200), SlotCode) WHERE SlotLabel IS NULL;
ALTER TABLE dbo.DocumentSlot ALTER COLUMN SlotLabel nvarchar(200) NOT NULL;

ALTER TABLE dbo.DocumentSlot
ADD CONSTRAINT CK_DocumentSlot_ApplicantUploadMode CHECK
        (ApplicantUploadMode IN (''CLOSED'', ''MISSING'', ''REPLACEMENT'')),
    CONSTRAINT CK_DocumentSlot_ApplicantOpenEvidence CHECK
        ((ApplicantUploadMode = ''CLOSED'')
         OR (ApplicantVisible = 1 AND LEN(UploadReason) > 0
             AND LEN(OpenedByIdentity) > 0 AND OpenedAtUtc IS NOT NULL)),
    CONSTRAINT CK_DocumentSlot_ApplicantLabel CHECK (LEN(SlotLabel) > 0),
    CONSTRAINT CK_DocumentSlot_NoVisibleRecommendationSlot CHECK
        (ApplicantVisible = 0 OR SlotCode NOT LIKE ''%RECOMMEND%'');
');

CREATE TABLE dbo.ApplicantDocumentSubmission
(
    ApplicantDocumentSubmissionId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantDocumentSubmission_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    DocumentSlotId uniqueidentifier NOT NULL,
    DocumentVersionId uniqueidentifier NOT NULL,
    ApplicantSessionId uniqueidentifier NOT NULL,
    SubmissionStatus varchar(12) NOT NULL,
    SubmittedDisplayName nvarchar(255) NOT NULL,
    SubmittedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantDocumentSubmission_SubmittedAtUtc DEFAULT SYSUTCDATETIME(),
    ReviewedByIdentity nvarchar(255) NULL,
    ReviewedAtUtc datetime2(7) NULL,
    ReviewReason nvarchar(1000) NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantDocumentSubmission_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicantDocumentSubmission PRIMARY KEY (ApplicantDocumentSubmissionId),
    CONSTRAINT FK_ApplicantDocumentSubmission_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT FK_ApplicantDocumentSubmission_Slot FOREIGN KEY (DocumentSlotId)
        REFERENCES dbo.DocumentSlot (DocumentSlotId),
    CONSTRAINT FK_ApplicantDocumentSubmission_Version FOREIGN KEY (DocumentVersionId)
        REFERENCES dbo.DocumentVersion (DocumentVersionId),
    CONSTRAINT FK_ApplicantDocumentSubmission_Session FOREIGN KEY (ApplicantSessionId)
        REFERENCES dbo.ApplicantSession (ApplicantSessionId),
    CONSTRAINT UQ_ApplicantDocumentSubmission_Version UNIQUE (DocumentVersionId),
    CONSTRAINT CK_ApplicantDocumentSubmission_Status CHECK
        (SubmissionStatus IN ('PENDING', 'ACCEPTED', 'REJECTED')),
    CONSTRAINT CK_ApplicantDocumentSubmission_Name CHECK (LEN(SubmittedDisplayName) > 0),
    CONSTRAINT CK_ApplicantDocumentSubmission_Review CHECK
        ((SubmissionStatus = 'PENDING' AND ReviewedByIdentity IS NULL AND ReviewedAtUtc IS NULL)
         OR (SubmissionStatus IN ('ACCEPTED', 'REJECTED')
             AND LEN(ReviewedByIdentity) > 0 AND ReviewedAtUtc IS NOT NULL))
);

EXEC(N'
CREATE TRIGGER dbo.TR_ApplicantReopenScope_OpenDocumentSlot
ON dbo.ApplicantReopenScope
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS
    (
        SELECT 1
        FROM inserted AS reopen_row
        WHERE reopen_row.ScopeType = ''DOCUMENT_SLOT''
          AND NOT EXISTS
          (
              SELECT 1 FROM dbo.DocumentSlot AS slot_row
              WHERE slot_row.ApplicationId = reopen_row.ApplicationId
                AND slot_row.SlotCode = reopen_row.ScopeCode
                AND slot_row.ApplicantVisible = 1
                AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
          )
    )
        THROW 52420, ''The applicant document slot is unavailable.'', 1;

    UPDATE slot_row
    SET ApplicantUploadMode = ''REPLACEMENT'',
        UploadReason = reopen_row.Reason,
        OpenedByIdentity = reopen_row.ReopenedByIdentity,
        OpenedAtUtc = reopen_row.ReopenedAtUtc
    FROM dbo.DocumentSlot AS slot_row
    JOIN inserted AS reopen_row
      ON reopen_row.ApplicationId = slot_row.ApplicationId
     AND reopen_row.ScopeCode = slot_row.SlotCode
     AND reopen_row.ScopeType = ''DOCUMENT_SLOT''
    WHERE slot_row.ApplicantVisible = 1
      AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%'';
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ValidateApplicantUploadSlot
    @SessionTokenSha256 binary(32),
    @DocumentSlotId uniqueidentifier,
    @ExpectedRowVersion binary(8)
AS
BEGIN
    SET NOCOUNT ON;
    SELECT
        slot_row.DocumentSlotId,
        slot_row.SlotCode,
        slot_row.ApplicantUploadMode,
        slot_row.RowVersion,
        slot_row.ActiveDocumentVersionId
    FROM dbo.ApplicantSession AS session_row
    JOIN dbo.DocumentSlot AS slot_row
      ON slot_row.ApplicationId = session_row.ApplicationId
    LEFT JOIN dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
      ON visible_version.ApplicationId = slot_row.ApplicationId
     AND visible_version.DocumentSlotId = slot_row.DocumentSlotId
     AND visible_version.DocumentVersionId = slot_row.ActiveDocumentVersionId
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME()
      AND slot_row.DocumentSlotId = @DocumentSlotId
      AND slot_row.ApplicantVisible = 1
      AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
      AND slot_row.ApplicantUploadMode IN (''MISSING'', ''REPLACEMENT'')
      AND slot_row.RowVersion = @ExpectedRowVersion
      AND (slot_row.ActiveDocumentVersionId IS NULL
           OR visible_version.DocumentVersionId IS NOT NULL);
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantDocumentSlots
    @SessionTokenSha256 binary(32)
AS
BEGIN
    SET NOCOUNT ON;
    SELECT
        slot_row.DocumentSlotId,
        slot_row.SlotCode,
        slot_row.SlotLabel,
        slot_row.RequiredForCompletion,
        slot_row.ApplicantUploadMode,
        slot_row.RowVersion,
        slot_row.ActiveDocumentVersionId
    FROM dbo.ApplicantSession AS session_row
    JOIN dbo.DocumentSlot AS slot_row
      ON slot_row.ApplicationId = session_row.ApplicationId
    LEFT JOIN dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
      ON visible_version.ApplicationId = slot_row.ApplicationId
     AND visible_version.DocumentSlotId = slot_row.DocumentSlotId
     AND visible_version.DocumentVersionId = slot_row.ActiveDocumentVersionId
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME()
      AND slot_row.ApplicantVisible = 1
      AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
      AND (slot_row.ActiveDocumentVersionId IS NULL
           OR visible_version.DocumentVersionId IS NOT NULL)
    ORDER BY slot_row.SlotCode;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.ValidateApplicantFinalDocuments
    @ApplicationId uniqueidentifier,
    @ManifestJson nvarchar(max)
AS
BEGIN
    SET NOCOUNT ON;

    IF EXISTS
    (
        SELECT 1
        FROM dbo.DocumentSlot AS slot_row
        WHERE slot_row.ApplicationId = @ApplicationId
          AND slot_row.ApplicantVisible = 1
          AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
          AND slot_row.ApplicantUploadMode <> ''CLOSED''
    )
        THROW 52430, ''An applicant document slot is still open.'', 1;

    IF EXISTS
    (
        SELECT 1
        FROM dbo.DocumentSlot AS slot_row
        OUTER APPLY
        (
            SELECT TOP (1) submission_row.SubmissionStatus
            FROM dbo.ApplicantDocumentSubmission AS submission_row
            WHERE submission_row.DocumentSlotId = slot_row.DocumentSlotId
            ORDER BY submission_row.SubmittedAtUtc DESC,
                     submission_row.ApplicantDocumentSubmissionId DESC
        ) AS latest_submission
        WHERE slot_row.ApplicationId = @ApplicationId
          AND slot_row.ApplicantVisible = 1
          AND latest_submission.SubmissionStatus IN (''PENDING'', ''REJECTED'')
    )
        THROW 52431, ''An applicant document submission is unresolved.'', 1;

    IF EXISTS
    (
        SELECT 1
        FROM dbo.DocumentSlot AS slot_row
        WHERE slot_row.ApplicationId = @ApplicationId
          AND slot_row.ApplicantVisible = 1
          AND slot_row.RequiredForCompletion = 1
          AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
          AND slot_row.ActiveDocumentVersionId IS NULL
    )
        THROW 52432, ''A required applicant document is missing.'', 1;

    IF EXISTS
    (
        SELECT 1
        FROM dbo.DocumentSlot AS slot_row
        WHERE slot_row.ApplicationId = @ApplicationId
          AND slot_row.ApplicantVisible = 1
          AND slot_row.ActiveDocumentVersionId IS NOT NULL
          AND NOT EXISTS
              (SELECT 1 FROM dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
               WHERE visible_version.ApplicationId = @ApplicationId
                 AND visible_version.DocumentSlotId = slot_row.DocumentSlotId
                 AND visible_version.DocumentVersionId = slot_row.ActiveDocumentVersionId)
    )
        THROW 52433, ''A confidential document cannot enter applicant finalization.'', 1;

    IF (SELECT COUNT_BIG(*) FROM OPENJSON(@ManifestJson, ''$.documents'')) <>
       (
           SELECT COUNT_BIG(*)
           FROM dbo.DocumentSlot AS slot_row
           JOIN dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
             ON visible_version.ApplicationId = slot_row.ApplicationId
            AND visible_version.DocumentSlotId = slot_row.DocumentSlotId
            AND visible_version.DocumentVersionId = slot_row.ActiveDocumentVersionId
           WHERE slot_row.ApplicationId = @ApplicationId
             AND slot_row.ApplicantVisible = 1
             AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
       )
        THROW 52434, ''The applicant-document manifest is incomplete.'', 1;

    IF EXISTS
    (
        SELECT 1
        FROM dbo.DocumentSlot AS slot_row
        JOIN dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
          ON visible_version.ApplicationId = slot_row.ApplicationId
         AND visible_version.DocumentSlotId = slot_row.DocumentSlotId
         AND visible_version.DocumentVersionId = slot_row.ActiveDocumentVersionId
        JOIN dbo.StoredObject AS object_row
          ON object_row.StoredObjectId = visible_version.StoredObjectId
        WHERE slot_row.ApplicationId = @ApplicationId
          AND slot_row.ApplicantVisible = 1
          AND NOT EXISTS
          (
              SELECT 1
              FROM OPENJSON(@ManifestJson, ''$.documents'')
              WITH
              (
                  SlotCode varchar(80) ''$.slotCode'',
                  DocumentVersionId uniqueidentifier ''$.documentVersionId'',
                  PlaintextSha256 varchar(64) ''$.plaintextSha256''
              ) AS manifest_document
              WHERE manifest_document.SlotCode = slot_row.SlotCode
                AND manifest_document.DocumentVersionId = visible_version.DocumentVersionId
                AND object_row.PlaintextSha256 =
                    CONVERT(binary(32), manifest_document.PlaintextSha256, 2)
          )
    )
        THROW 52435, ''An applicant document is missing or stale.'', 1;
END;
');

GRANT EXECUTE ON dbo.ValidateApplicantUploadSlot TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetApplicantDocumentSlots TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.ValidateApplicantFinalDocuments TO EHFFinalConfirmationProcedureExecutor;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantDocumentSubmission TO EHFApplicationRuntime;
