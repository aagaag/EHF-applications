SET NOCOUNT ON;
SET XACT_ABORT ON;

/* Additive evaluation storage. Legacy 2026 writes remain valid and are mirrored. */
ALTER TABLE dbo.Application ADD CONSTRAINT UQ_Application_CallApplication
    UNIQUE (FellowshipCallId, ApplicationId);

CREATE TABLE dbo.FellowshipCallEvaluator
(
    FellowshipCallEvaluatorId uniqueidentifier NOT NULL
        CONSTRAINT DF_FellowshipCallEvaluator_Id DEFAULT NEWSEQUENTIALID(),
    FellowshipCallId uniqueidentifier NOT NULL,
    ActorEntraObjectId uniqueidentifier NOT NULL,
    DisplayName nvarchar(120) NOT NULL,
    DisplayOrder int NOT NULL,
    IsActive bit NOT NULL CONSTRAINT DF_FellowshipCallEvaluator_IsActive DEFAULT 1,
    LegacyTrusteeCode varchar(16) NULL,
    CreatedAtUtc datetime2(7) NOT NULL CONSTRAINT DF_FellowshipCallEvaluator_Created DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_FellowshipCallEvaluator PRIMARY KEY (FellowshipCallEvaluatorId),
    CONSTRAINT UQ_FellowshipCallEvaluator_CallId UNIQUE (FellowshipCallId, FellowshipCallEvaluatorId),
    CONSTRAINT UQ_FellowshipCallEvaluator_Owner UNIQUE (FellowshipCallId, ActorEntraObjectId),
    CONSTRAINT UQ_FellowshipCallEvaluator_Order UNIQUE (FellowshipCallId, DisplayOrder),
    CONSTRAINT FK_FellowshipCallEvaluator_Call FOREIGN KEY (FellowshipCallId)
        REFERENCES dbo.FellowshipCall (FellowshipCallId),
    CONSTRAINT CK_FellowshipCallEvaluator_Name CHECK (LEN(LTRIM(RTRIM(DisplayName))) > 0),
    CONSTRAINT CK_FellowshipCallEvaluator_Order CHECK (DisplayOrder > 0)
);
CREATE UNIQUE INDEX UX_FellowshipCallEvaluator_Legacy
    ON dbo.FellowshipCallEvaluator(FellowshipCallId, LegacyTrusteeCode)
    WHERE LegacyTrusteeCode IS NOT NULL;

CREATE TABLE dbo.CallEvaluationSelection
(
    FellowshipCallId uniqueidentifier NOT NULL,
    ApplicationId uniqueidentifier NOT NULL,
    FellowshipCallEvaluatorId uniqueidentifier NOT NULL,
    GroupCode char(1) NULL,
    ModifiedByIdentity nvarchar(255) NOT NULL,
    RecordedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_CallEvaluationSelection_Recorded DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_CallEvaluationSelection PRIMARY KEY
        (FellowshipCallId, ApplicationId, FellowshipCallEvaluatorId),
    CONSTRAINT FK_CallEvaluationSelection_Application
        FOREIGN KEY (FellowshipCallId, ApplicationId)
        REFERENCES dbo.Application (FellowshipCallId, ApplicationId),
    CONSTRAINT FK_CallEvaluationSelection_Evaluator
        FOREIGN KEY (FellowshipCallId, FellowshipCallEvaluatorId)
        REFERENCES dbo.FellowshipCallEvaluator (FellowshipCallId, FellowshipCallEvaluatorId),
    CONSTRAINT CK_CallEvaluationSelection_Group CHECK (GroupCode IN ('A','B','C') OR GroupCode IS NULL),
    CONSTRAINT CK_CallEvaluationSelection_Actor CHECK (LEN(ModifiedByIdentity) > 0)
);

DECLARE @LegacyCallId uniqueidentifier =
    (SELECT FellowshipCallId FROM dbo.FellowshipCall WHERE CallCode = N'EHF-2026');
IF @LegacyCallId IS NULL THROW 54900, 'The 2026 fellowship call is missing.', 1;

INSERT dbo.FellowshipCallEvaluator
    (FellowshipCallId, ActorEntraObjectId, DisplayName, DisplayOrder, LegacyTrusteeCode)
SELECT @LegacyCallId, ActorEntraObjectId, DisplayName,
       CASE TrusteeCode WHEN 'ricky' THEN 1 WHEN 'magda' THEN 2 WHEN 'adriano' THEN 3 END,
       TrusteeCode
FROM dbo.ShortlistTrustee;
IF @@ROWCOUNT <> 3 THROW 54901, 'The existing evaluator roster is incomplete.', 1;

INSERT dbo.CallEvaluationSelection
    (FellowshipCallId, ApplicationId, FellowshipCallEvaluatorId,
     GroupCode, ModifiedByIdentity, RecordedAtUtc)
SELECT @LegacyCallId, old.ApplicationId, reviewer.FellowshipCallEvaluatorId,
       old.GroupCode, old.ModifiedByIdentity, old.RecordedAtUtc
FROM dbo.TrusteeShortlistSelection AS old
JOIN dbo.Application AS application_row
  ON application_row.ApplicationId = old.ApplicationId
 AND application_row.FellowshipCallId = @LegacyCallId
JOIN dbo.FellowshipCallEvaluator AS reviewer
  ON reviewer.FellowshipCallId = @LegacyCallId
 AND reviewer.LegacyTrusteeCode = old.TrusteeCode;

IF EXISTS (
    SELECT 1 FROM dbo.TrusteeShortlistSelection AS old
    JOIN dbo.Application AS application_row ON application_row.ApplicationId = old.ApplicationId
    WHERE application_row.FellowshipCallId = @LegacyCallId
      AND NOT EXISTS (
          SELECT 1 FROM dbo.CallEvaluationSelection AS current_row
          JOIN dbo.FellowshipCallEvaluator AS reviewer
            ON reviewer.FellowshipCallEvaluatorId = current_row.FellowshipCallEvaluatorId
          WHERE current_row.FellowshipCallId = @LegacyCallId
            AND current_row.ApplicationId = old.ApplicationId
            AND reviewer.LegacyTrusteeCode = old.TrusteeCode
            AND (current_row.GroupCode = old.GroupCode OR
                 (current_row.GroupCode IS NULL AND old.GroupCode IS NULL))
            AND current_row.ModifiedByIdentity = old.ModifiedByIdentity
            AND current_row.RecordedAtUtc = old.RecordedAtUtc
      )
) THROW 54902, 'The 2026 evaluation backfill is incomplete.', 1;

EXEC(N'
CREATE OR ALTER TRIGGER dbo.TrusteeShortlistSelection_CallEvaluationMirror
ON dbo.TrusteeShortlistSelection
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE destination
       SET GroupCode = source_row.GroupCode,
           ModifiedByIdentity = source_row.ModifiedByIdentity,
           RecordedAtUtc = source_row.RecordedAtUtc
    FROM dbo.CallEvaluationSelection AS destination
    JOIN inserted AS source_row ON source_row.ApplicationId = destination.ApplicationId
    JOIN dbo.FellowshipCallEvaluator AS reviewer
      ON reviewer.FellowshipCallId = destination.FellowshipCallId
     AND reviewer.FellowshipCallEvaluatorId = destination.FellowshipCallEvaluatorId
     AND reviewer.LegacyTrusteeCode = source_row.TrusteeCode;

    INSERT dbo.CallEvaluationSelection
        (FellowshipCallId, ApplicationId, FellowshipCallEvaluatorId,
         GroupCode, ModifiedByIdentity, RecordedAtUtc)
    SELECT reviewer.FellowshipCallId, source_row.ApplicationId,
           reviewer.FellowshipCallEvaluatorId, source_row.GroupCode,
           source_row.ModifiedByIdentity, source_row.RecordedAtUtc
    FROM inserted AS source_row
    JOIN dbo.Application AS application_row ON application_row.ApplicationId = source_row.ApplicationId
    JOIN dbo.FellowshipCallEvaluator AS reviewer
      ON reviewer.FellowshipCallId = application_row.FellowshipCallId
     AND reviewer.LegacyTrusteeCode = source_row.TrusteeCode
    WHERE NOT EXISTS (
        SELECT 1 FROM dbo.CallEvaluationSelection AS destination WITH (UPDLOCK, HOLDLOCK)
        WHERE destination.FellowshipCallId = reviewer.FellowshipCallId
          AND destination.ApplicationId = source_row.ApplicationId
          AND destination.FellowshipCallEvaluatorId = reviewer.FellowshipCallEvaluatorId
    );
END;
');
EXEC(N'
CREATE OR ALTER PROCEDURE dbo.GetCallEvaluationOverview
    @FellowshipCallId uniqueidentifier,
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (
        SELECT 1 FROM dbo.FellowshipCallGroupGrant
        WHERE FellowshipCallId = @FellowshipCallId
          AND GroupName = @ActorGroup AND IsActive = 1
          AND AccessRole IN (''READ'',''ADMINISTER'')
    ) THROW 54903, ''The call is unavailable.'', 1;

    SELECT CONVERT(nvarchar(36), FellowshipCallEvaluatorId), DisplayName, DisplayOrder
    FROM dbo.FellowshipCallEvaluator
    WHERE FellowshipCallId = @FellowshipCallId AND IsActive = 1
    ORDER BY DisplayOrder;

    ;WITH numbered AS (
        SELECT application_row.FellowshipCallId, application_row.ApplicationId,
               CONCAT(applicant.LegalGivenNames, N'' '', applicant.LegalFamilyName) AS ApplicantName,
               CONCAT(call_row.CallCode, N''-'', RIGHT(N''000'' + CONVERT(nvarchar(10),
                   ROW_NUMBER() OVER (ORDER BY applicant.LegalFamilyName,
                       applicant.LegalGivenNames, application_row.ApplicationId)), 3)) AS ApplicationNumber
        FROM dbo.Application AS application_row
        JOIN dbo.Applicant AS applicant ON applicant.ApplicantId = application_row.ApplicantId
        JOIN dbo.FellowshipCall AS call_row ON call_row.FellowshipCallId = application_row.FellowshipCallId
        WHERE application_row.FellowshipCallId = @FellowshipCallId
    )
    SELECT CONVERT(nvarchar(36), numbered.ApplicationId), numbered.ApplicantName,
           numbered.ApplicationNumber,
           CONVERT(nvarchar(36), reviewer.FellowshipCallEvaluatorId), selection_row.GroupCode
    FROM numbered
    LEFT JOIN dbo.FellowshipCallEvaluator AS reviewer
      ON reviewer.FellowshipCallId = numbered.FellowshipCallId AND reviewer.IsActive = 1
    LEFT JOIN dbo.CallEvaluationSelection AS selection_row
      ON selection_row.FellowshipCallId = numbered.FellowshipCallId
     AND selection_row.ApplicationId = numbered.ApplicationId
     AND selection_row.FellowshipCallEvaluatorId = reviewer.FellowshipCallEvaluatorId
    ORDER BY numbered.ApplicantName, numbered.ApplicationId, reviewer.DisplayOrder;
END;
');
GRANT EXECUTE ON dbo.GetCallEvaluationOverview TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.FellowshipCallEvaluator TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.CallEvaluationSelection TO EHFApplicationRuntime;
