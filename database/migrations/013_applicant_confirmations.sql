SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE TABLE dbo.ApplicantSectionConfirmation
(
    ApplicantSectionConfirmationId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantSectionConfirmation_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    SectionCode varchar(80) NOT NULL,
    CanonicalSectionSha256 binary(32) NOT NULL,
    DraftRowVersion binary(8) NOT NULL,
    ConfirmedByIdentity nvarchar(255) NOT NULL,
    ConfirmedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantSectionConfirmation_ConfirmedAtUtc DEFAULT SYSUTCDATETIME(),
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantSectionConfirmation_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ApplicantSectionConfirmation PRIMARY KEY (ApplicantSectionConfirmationId),
    CONSTRAINT FK_ApplicantSectionConfirmation_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT UQ_ApplicantSectionConfirmation_Version UNIQUE
        (ApplicationId, SectionCode, CanonicalSectionSha256),
    CONSTRAINT CK_ApplicantSectionConfirmation_Section CHECK (LEN(SectionCode) > 0),
    CONSTRAINT CK_ApplicantSectionConfirmation_Actor CHECK (LEN(ConfirmedByIdentity) > 0)
);

EXEC(N'
CREATE TRIGGER dbo.TR_ApplicantSectionConfirmation_AppendOnly
ON dbo.ApplicantSectionConfirmation
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 52120, ''Applicant section confirmations are append-only.'', 1;
END;
');

CREATE TABLE dbo.ApplicantFinalConfirmation
(
    ApplicantFinalConfirmationId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantFinalConfirmation_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    ManifestJson nvarchar(max) NOT NULL,
    ManifestSha256 binary(32) NOT NULL,
    ConfirmedByIdentity nvarchar(255) NOT NULL,
    ConfirmedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantFinalConfirmation_ConfirmedAtUtc DEFAULT SYSUTCDATETIME(),
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantFinalConfirmation_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    SupersededAtUtc datetime2(7) NULL,
    CONSTRAINT PK_ApplicantFinalConfirmation PRIMARY KEY (ApplicantFinalConfirmationId),
    CONSTRAINT FK_ApplicantFinalConfirmation_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT CK_ApplicantFinalConfirmation_Manifest CHECK (ISJSON(ManifestJson) = 1),
    CONSTRAINT CK_ApplicantFinalConfirmation_Actor CHECK (LEN(ConfirmedByIdentity) > 0),
    CONSTRAINT CK_ApplicantFinalConfirmation_Superseded CHECK
        (SupersededAtUtc IS NULL OR SupersededAtUtc >= ConfirmedAtUtc)
);

CREATE UNIQUE INDEX UX_ApplicantFinalConfirmation_Active
ON dbo.ApplicantFinalConfirmation (ApplicationId)
WHERE SupersededAtUtc IS NULL;

CREATE TABLE dbo.ApplicantReopenScope
(
    ApplicantReopenScopeId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantReopenScope_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    ScopeType varchar(20) NOT NULL,
    ScopeCode varchar(80) NOT NULL,
    Reason nvarchar(1000) NOT NULL,
    ReopenedByIdentity nvarchar(255) NOT NULL,
    ReopenedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantReopenScope_ReopenedAtUtc DEFAULT SYSUTCDATETIME(),
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantReopenScope_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    ClosedAtUtc datetime2(7) NULL,
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicantReopenScope PRIMARY KEY (ApplicantReopenScopeId),
    CONSTRAINT FK_ApplicantReopenScope_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT CK_ApplicantReopenScope_Type CHECK (ScopeType IN ('SECTION', 'DOCUMENT_SLOT')),
    CONSTRAINT CK_ApplicantReopenScope_Code CHECK (LEN(ScopeCode) > 0),
    CONSTRAINT CK_ApplicantReopenScope_Reason CHECK (LEN(Reason) > 0),
    CONSTRAINT CK_ApplicantReopenScope_Actor CHECK (LEN(ReopenedByIdentity) > 0),
    CONSTRAINT CK_ApplicantReopenScope_Closed CHECK
        (ClosedAtUtc IS NULL OR ClosedAtUtc >= ReopenedAtUtc)
);

CREATE USER EHFFinalConfirmationProcedureExecutor WITHOUT LOGIN;
DENY IMPERSONATE ON USER::EHFFinalConfirmationProcedureExecutor TO public;
GRANT UPDATE ON dbo.ApplicantFinalConfirmation TO EHFFinalConfirmationProcedureExecutor;
GRANT UPDATE ON dbo.Application TO EHFFinalConfirmationProcedureExecutor;
GRANT INSERT ON dbo.ApplicantReopenScope TO EHFFinalConfirmationProcedureExecutor;
GRANT UPDATE ON dbo.ApplicantReopenScope TO EHFFinalConfirmationProcedureExecutor;
GRANT INSERT ON dbo.ApplicantSectionConfirmation TO EHFFinalConfirmationProcedureExecutor;
GRANT INSERT ON dbo.ApplicantFinalConfirmation TO EHFFinalConfirmationProcedureExecutor;
GRANT INSERT ON dbo.AuditEvent TO EHFFinalConfirmationProcedureExecutor;

EXEC(N'
CREATE TRIGGER dbo.TR_ApplicantFinalConfirmation_AppendOnly
ON dbo.ApplicantFinalConfirmation
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM deleted) AND NOT EXISTS (SELECT 1 FROM inserted)
        THROW 52121, ''Applicant final confirmations cannot be deleted.'', 1;
    IF USER_NAME() <> N''EHFFinalConfirmationProcedureExecutor''
        THROW 52122, ''Applicant final confirmations are append-only.'', 1;
    IF EXISTS
    (
        SELECT 1
        FROM inserted AS next_row
        JOIN deleted AS prior_row
          ON prior_row.ApplicantFinalConfirmationId = next_row.ApplicantFinalConfirmationId
        WHERE prior_row.ApplicationId <> next_row.ApplicationId
           OR prior_row.ManifestSha256 <> next_row.ManifestSha256
           OR prior_row.ManifestJson <> next_row.ManifestJson
           OR prior_row.ConfirmedByIdentity <> next_row.ConfirmedByIdentity
           OR prior_row.ConfirmedAtUtc <> next_row.ConfirmedAtUtc
           OR prior_row.SupersededAtUtc IS NOT NULL
           OR next_row.SupersededAtUtc IS NULL
    )
        THROW 52123, ''Only one-way confirmation supersession is allowed.'', 1;
    UPDATE target_row
    SET SupersededAtUtc = next_row.SupersededAtUtc
    FROM dbo.ApplicantFinalConfirmation AS target_row
    JOIN inserted AS next_row
      ON next_row.ApplicantFinalConfirmationId = target_row.ApplicantFinalConfirmationId;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ReopenApplicantScope
    @ApplicationId uniqueidentifier,
    @ScopeType varchar(20),
    @ScopeCode varchar(80),
    @Reason nvarchar(1000),
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128)
WITH EXECUTE AS ''EHFFinalConfirmationProcedureExecutor''
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @ActorGroup <> N''EHF-Administrators''
        THROW 52124, ''Only an EHF administrator may reopen applicant work.'', 1;
    IF @ScopeType NOT IN (''SECTION'', ''DOCUMENT_SLOT'')
        THROW 52125, ''The reopen scope type is invalid.'', 1;
    IF NULLIF(LTRIM(RTRIM(@ScopeCode)), '''') IS NULL OR NULLIF(LTRIM(RTRIM(@Reason)), N'''') IS NULL
        THROW 52126, ''A reopen scope and reason are required.'', 1;
    IF NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
        THROW 52139, ''The reopening administrator identity is required.'', 1;
    IF @ScopeType = ''SECTION'' AND @ScopeCode NOT IN
       (''identity'', ''employment'', ''qualifications'', ''publications'', ''contribution'')
        THROW 52140, ''The applicant section is invalid.'', 1;

    BEGIN TRANSACTION;
    BEGIN TRY
        IF NOT EXISTS (SELECT 1 FROM dbo.Application WITH (UPDLOCK, HOLDLOCK) WHERE ApplicationId = @ApplicationId)
            THROW 52127, ''The application is unavailable.'', 1;
        UPDATE dbo.ApplicantFinalConfirmation
        SET SupersededAtUtc = SYSUTCDATETIME()
        WHERE ApplicationId = @ApplicationId AND SupersededAtUtc IS NULL;
        INSERT dbo.ApplicantReopenScope
            (ApplicationId, ScopeType, ScopeCode, Reason, ReopenedByIdentity)
        VALUES (@ApplicationId, @ScopeType, @ScopeCode, @Reason, @ActorIdentity);
        INSERT dbo.AuditEvent
            (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
        VALUES
            (@ApplicationId, ''APPLICANT_SCOPE_REOPENED'', @ActorIdentity,
             ''Application'', @ApplicationId,
             (SELECT @ApplicationId AS applicationId, ''IN_REVIEW'' AS status
              FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));
        UPDATE dbo.Application
        SET ApplicationStatus = ''IN_REVIEW'', ConfirmedAtUtc = NULL, UpdatedAtUtc = SYSUTCDATETIME()
        WHERE ApplicationId = @ApplicationId;
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ConfirmApplicantSection
    @SessionTokenSha256 binary(32),
    @SectionCode varchar(80),
    @CanonicalSectionSha256 binary(32),
    @DraftRowVersion binary(8)
WITH EXECUTE AS ''EHFFinalConfirmationProcedureExecutor''
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @ApplicationId uniqueidentifier;
    SELECT @ApplicationId = session_row.ApplicationId
    FROM dbo.ApplicantSession AS session_row
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME();
    IF @ApplicationId IS NULL
        THROW 52128, ''The applicant session is unavailable.'', 1;
    IF @SectionCode NOT IN (''identity'', ''employment'', ''qualifications'', ''publications'', ''contribution'')
        THROW 52129, ''The applicant section is invalid.'', 1;
    DECLARE @StoredDraftJson nvarchar(max);
    SELECT @StoredDraftJson = DraftJson
        FROM dbo.ApplicantSectionDraft
        WHERE ApplicationId = @ApplicationId
          AND SectionCode = @SectionCode
          AND RowVersion = @DraftRowVersion;
    IF @StoredDraftJson IS NULL
        THROW 52130, ''The applicant section changed before confirmation.'', 1;
    IF HASHBYTES(''SHA2_256'', CONVERT(varbinary(max), @StoredDraftJson)) <>
       @CanonicalSectionSha256
        THROW 52141, ''The applicant section hash is invalid.'', 1;
    IF NOT EXISTS
    (
        SELECT 1 FROM dbo.ApplicantSectionConfirmation
        WHERE ApplicationId = @ApplicationId
          AND SectionCode = @SectionCode
          AND CanonicalSectionSha256 = @CanonicalSectionSha256
    )
        INSERT dbo.ApplicantSectionConfirmation
            (ApplicationId, SectionCode, CanonicalSectionSha256, DraftRowVersion, ConfirmedByIdentity)
        VALUES
            (@ApplicationId, @SectionCode, @CanonicalSectionSha256, @DraftRowVersion, N''APPLICANT'');
    SELECT ApplicantSectionConfirmationId, SectionCode, CanonicalSectionSha256,
           DraftRowVersion, ConfirmedAtUtc
    FROM dbo.ApplicantSectionConfirmation
    WHERE ApplicationId = @ApplicationId
      AND SectionCode = @SectionCode
      AND CanonicalSectionSha256 = @CanonicalSectionSha256;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ValidateApplicantFinalDocuments
    @ApplicationId uniqueidentifier,
    @ManifestJson nvarchar(max)
AS
BEGIN
    SET NOCOUNT ON;
    THROW 52142, ''Applicant document finalization is unavailable until the document-slot migration completes.'', 1;
END;
');

GRANT EXECUTE ON dbo.ValidateApplicantFinalDocuments TO EHFFinalConfirmationProcedureExecutor;

EXEC(N'
CREATE PROCEDURE dbo.SubmitApplicantFinalConfirmation
    @SessionTokenSha256 binary(32),
    @ManifestJson nvarchar(max),
    @ManifestSha256 binary(32)
WITH EXECUTE AS ''EHFFinalConfirmationProcedureExecutor''
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF ISJSON(@ManifestJson) <> 1
        THROW 52131, ''The confirmation manifest is invalid.'', 1;
    IF HASHBYTES(''SHA2_256'', CONVERT(varbinary(max), @ManifestJson)) <> @ManifestSha256
        THROW 52132, ''The confirmation manifest hash is invalid.'', 1;

    BEGIN TRANSACTION;
    BEGIN TRY
        DECLARE @ApplicationId uniqueidentifier, @ConfirmationId uniqueidentifier;
        SELECT @ApplicationId = session_row.ApplicationId
        FROM dbo.ApplicantSession AS session_row WITH (UPDLOCK, HOLDLOCK)
        WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
          AND session_row.RevokedAtUtc IS NULL
          AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
          AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME();
        IF @ApplicationId IS NULL
            THROW 52133, ''The applicant session is unavailable.'', 1;

        SELECT @ConfirmationId = ApplicantFinalConfirmationId
        FROM dbo.ApplicantFinalConfirmation
        WHERE ApplicationId = @ApplicationId
          AND ManifestSha256 = @ManifestSha256
          AND SupersededAtUtc IS NULL;
        IF @ConfirmationId IS NOT NULL
        BEGIN
            SELECT ApplicantFinalConfirmationId, ManifestSha256, ConfirmedAtUtc
            FROM dbo.ApplicantFinalConfirmation
            WHERE ApplicantFinalConfirmationId = @ConfirmationId;
            COMMIT TRANSACTION;
            RETURN;
        END;

        IF EXISTS
        (
            SELECT 1 FROM dbo.ApplicantFinalConfirmation
            WHERE ApplicationId = @ApplicationId AND SupersededAtUtc IS NULL
        )
            THROW 52134, ''The application already has a different active confirmation.'', 1;

        IF (SELECT COUNT_BIG(*) FROM OPENJSON(@ManifestJson, ''$.sections'')) <> 5
            THROW 52135, ''Every applicant section must be represented once.'', 1;
        IF EXISTS
        (
            SELECT required_section.SectionCode
            FROM (VALUES
                (''identity''), (''employment''), (''qualifications''),
                (''publications''), (''contribution'')
            ) AS required_section(SectionCode)
            WHERE NOT EXISTS
            (
                SELECT 1
                FROM OPENJSON(@ManifestJson, ''$.sections'')
                WITH
                (
                    SectionCode varchar(80) ''$.section'',
                    DraftVersion bigint ''$.rowVersion'',
                    CanonicalSha256 varchar(64) ''$.canonicalSha256''
                ) AS manifest_section
                JOIN dbo.ApplicantSectionDraft AS draft_row
                  ON draft_row.ApplicationId = @ApplicationId
                 AND draft_row.SectionCode = manifest_section.SectionCode
                JOIN dbo.ApplicantSectionConfirmation AS confirmation_row
                  ON confirmation_row.ApplicationId = draft_row.ApplicationId
                 AND confirmation_row.SectionCode = draft_row.SectionCode
                 AND confirmation_row.DraftRowVersion = draft_row.RowVersion
                 AND confirmation_row.CanonicalSectionSha256 = CONVERT(binary(32), manifest_section.CanonicalSha256, 2)
                WHERE manifest_section.SectionCode = required_section.SectionCode
            )
        )
            THROW 52136, ''An applicant section is missing or stale.'', 1;

        EXEC dbo.ValidateApplicantFinalDocuments
            @ApplicationId = @ApplicationId,
            @ManifestJson = @ManifestJson;

        SET @ConfirmationId = NEWID();
        INSERT dbo.ApplicantFinalConfirmation
            (ApplicantFinalConfirmationId, ApplicationId, ManifestJson, ManifestSha256, ConfirmedByIdentity)
        VALUES
            (@ConfirmationId, @ApplicationId, @ManifestJson, @ManifestSha256, N''APPLICANT'');
        UPDATE dbo.Application
        SET ApplicationStatus = ''CONFIRMED'', ConfirmedAtUtc = SYSUTCDATETIME(),
            UpdatedAtUtc = SYSUTCDATETIME()
        WHERE ApplicationId = @ApplicationId;
        INSERT dbo.AuditEvent
            (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
        VALUES
            (@ApplicationId, ''APPLICANT_FINAL_SUBMISSION'', N''APPLICANT'',
             ''ApplicantFinalConfirmation'', @ConfirmationId,
             (SELECT @ApplicationId AS applicationId FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));
        UPDATE dbo.ApplicantReopenScope
        SET ClosedAtUtc = SYSUTCDATETIME()
        WHERE ApplicationId = @ApplicationId AND ClosedAtUtc IS NULL;
        SELECT ApplicantFinalConfirmationId, ManifestSha256, ConfirmedAtUtc
        FROM dbo.ApplicantFinalConfirmation
        WHERE ApplicantFinalConfirmationId = @ConfirmationId;
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

GRANT EXECUTE ON dbo.ConfirmApplicantSection TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.SubmitApplicantFinalConfirmation TO EHFApplicationRuntime;
DENY EXECUTE ON dbo.ReopenApplicantScope TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantSectionConfirmation TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantFinalConfirmation TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantReopenScope TO EHFApplicationRuntime;
