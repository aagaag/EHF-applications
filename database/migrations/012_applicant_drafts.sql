SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE TABLE dbo.ApplicantSectionDraft
(
    ApplicantSectionDraftId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantSectionDraft_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    SectionCode varchar(80) NOT NULL,
    DraftJson nvarchar(max) NOT NULL,
    SavedByIdentity nvarchar(255) NOT NULL,
    SavedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantSectionDraft_SavedAtUtc DEFAULT SYSUTCDATETIME(),
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantSectionDraft_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicantSectionDraft PRIMARY KEY (ApplicantSectionDraftId),
    CONSTRAINT FK_ApplicantSectionDraft_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT UQ_ApplicantSectionDraft_ApplicationSection UNIQUE (ApplicationId, SectionCode),
    CONSTRAINT CK_ApplicantSectionDraft_Section CHECK (LEN(SectionCode) > 0),
    CONSTRAINT CK_ApplicantSectionDraft_Json CHECK (ISJSON(DraftJson) = 1),
    CONSTRAINT CK_ApplicantSectionDraft_Actor CHECK (LEN(SavedByIdentity) > 0)
);

CREATE TABLE dbo.ApplicantFieldCorrection
(
    ApplicantFieldCorrectionId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantFieldCorrection_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    SectionCode varchar(80) NOT NULL,
    FieldCode varchar(120) NOT NULL,
    PreviousValueJson nvarchar(max) NULL,
    NewValueJson nvarchar(max) NOT NULL,
    CorrectedByIdentity nvarchar(255) NOT NULL,
    CorrectionSource varchar(20) NOT NULL,
    CorrectedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantFieldCorrection_CorrectedAtUtc DEFAULT SYSUTCDATETIME(),
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantFieldCorrection_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ApplicantFieldCorrection PRIMARY KEY (ApplicantFieldCorrectionId),
    CONSTRAINT FK_ApplicantFieldCorrection_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT CK_ApplicantFieldCorrection_Codes CHECK
        (LEN(SectionCode) > 0 AND LEN(FieldCode) > 0),
    CONSTRAINT CK_ApplicantFieldCorrection_Json CHECK
        ((PreviousValueJson IS NULL OR ISJSON(PreviousValueJson) = 1)
         AND ISJSON(NewValueJson) = 1),
    CONSTRAINT CK_ApplicantFieldCorrection_Source CHECK
        (CorrectionSource IN ('APPLICANT', 'ADMINISTRATOR')),
    CONSTRAINT CK_ApplicantFieldCorrection_Actor CHECK (LEN(CorrectedByIdentity) > 0)
);

EXEC(N'
CREATE TRIGGER dbo.TR_ApplicantFieldCorrection_AppendOnly
ON dbo.ApplicantFieldCorrection
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 52020, ''Applicant correction history is append-only.'', 1;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.SaveApplicantSectionDraft
    @SessionTokenSha256 binary(32),
    @SectionCode varchar(80),
    @DraftJson nvarchar(max),
    @ExpectedRowVersion binary(8) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    IF NULLIF(LTRIM(RTRIM(@SectionCode)), '''') IS NULL
        THROW 52021, ''An applicant section is required.'', 1;
    IF @SectionCode NOT IN (''identity'', ''employment'', ''qualifications'', ''publications'', ''contribution'')
        THROW 52023, ''The applicant section is invalid.'', 1;
    IF ISJSON(@DraftJson) <> 1
        THROW 52022, ''The applicant draft must be valid JSON.'', 1;
    BEGIN TRANSACTION;
    BEGIN TRY
        DECLARE @ApplicationId uniqueidentifier, @BeforeJson nvarchar(max),
                @ActualRowVersion binary(8), @Status varchar(20);
        SELECT @ApplicationId = session_row.ApplicationId,
               @Status = application_row.ApplicationStatus
        FROM dbo.ApplicantSession AS session_row WITH (UPDLOCK, HOLDLOCK)
        JOIN dbo.Application AS application_row WITH (UPDLOCK, HOLDLOCK)
          ON application_row.ApplicationId = session_row.ApplicationId
        WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
          AND session_row.RevokedAtUtc IS NULL
          AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
          AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME();
        IF @Status IS NULL THROW 52024, ''The application is unavailable.'', 1;
        IF @Status = ''CONFIRMED'' THROW 52025, ''The application is locked.'', 1;
        IF EXISTS
        (
            SELECT 1 FROM dbo.ApplicantFinalConfirmation
            WHERE ApplicationId = @ApplicationId
        )
        AND NOT EXISTS
        (
            SELECT 1 FROM dbo.ApplicantReopenScope
            WHERE ApplicationId = @ApplicationId
              AND ScopeType = ''SECTION''
              AND ScopeCode = @SectionCode
              AND ClosedAtUtc IS NULL
        )
            THROW 52027, ''The application section is locked.'', 1;

        SELECT @BeforeJson = DraftJson, @ActualRowVersion = RowVersion
        FROM dbo.ApplicantSectionDraft WITH (UPDLOCK, HOLDLOCK)
        WHERE ApplicationId = @ApplicationId AND SectionCode = @SectionCode;

        IF @ActualRowVersion IS NOT NULL AND
           (@ExpectedRowVersion IS NULL OR @ExpectedRowVersion <> @ActualRowVersion)
            THROW 52026, ''The applicant draft changed before this update.'', 1;
        IF @ActualRowVersion IS NULL AND @ExpectedRowVersion IS NOT NULL
            THROW 52026, ''The applicant draft changed before this update.'', 1;

        IF @ActualRowVersion IS NULL
            INSERT dbo.ApplicantSectionDraft
                (ApplicationId, SectionCode, DraftJson, SavedByIdentity)
            VALUES (@ApplicationId, @SectionCode, @DraftJson, N''APPLICANT'');
        ELSE
            UPDATE dbo.ApplicantSectionDraft
            SET DraftJson = @DraftJson,
                SavedByIdentity = N''APPLICANT'',
                SavedAtUtc = SYSUTCDATETIME()
            WHERE ApplicationId = @ApplicationId AND SectionCode = @SectionCode;

        INSERT dbo.ApplicantFieldCorrection
            (ApplicationId, SectionCode, FieldCode, PreviousValueJson, NewValueJson,
             CorrectedByIdentity, CorrectionSource)
        VALUES
            (@ApplicationId, @SectionCode, ''$'', @BeforeJson, @DraftJson,
             N''APPLICANT'', ''APPLICANT'');

        SELECT ApplicantSectionDraftId, ApplicationId, SectionCode, DraftJson, RowVersion
        FROM dbo.ApplicantSectionDraft
        WHERE ApplicationId = @ApplicationId AND SectionCode = @SectionCode;
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

GRANT EXECUTE ON dbo.SaveApplicantSectionDraft TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantSectionDraft TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantFieldCorrection TO EHFApplicationRuntime;
