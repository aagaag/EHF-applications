SET NOCOUNT ON;
SET XACT_ABORT ON;

ALTER TABLE dbo.CallEvaluationSelection ADD CommentText nvarchar(2000) NULL,
    CommentModifiedByIdentity nvarchar(255) NULL,
    CommentRecordedAtUtc datetime2(7) NULL;

ALTER TABLE dbo.CallEvaluationSelection ADD CONSTRAINT CK_CallEvaluationSelection_CommentAudit
    CHECK ((CommentText IS NULL AND CommentModifiedByIdentity IS NULL AND CommentRecordedAtUtc IS NULL)
        OR (CommentText IS NOT NULL AND CommentModifiedByIdentity IS NOT NULL AND CommentRecordedAtUtc IS NOT NULL));

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
    ) THROW 55000, ''The call is unavailable.'', 1;

    SELECT CONVERT(nvarchar(36), FellowshipCallEvaluatorId), DisplayName,
           DisplayOrder, LegacyTrusteeCode
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
           CONVERT(nvarchar(36), reviewer.FellowshipCallEvaluatorId),
           selection_row.GroupCode, selection_row.CommentText
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

EXEC(N'
CREATE OR ALTER PROCEDURE dbo.SetCallEvaluationComment
    @FellowshipCallId uniqueidentifier,
    @ApplicationId uniqueidentifier,
    @CommentText nvarchar(2000),
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128),
    @ActorEntraObjectId uniqueidentifier
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @EvaluatorId uniqueidentifier;
    DECLARE @BeforeHasComment bit = 0;
    DECLARE @AfterComment nvarchar(2000) = CASE
        WHEN NULLIF(LTRIM(RTRIM(@CommentText)), N'''') IS NULL THEN NULL ELSE @CommentText END;
    DECLARE @PayloadJson nvarchar(max);

    IF @ActorEntraObjectId IS NULL OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
        THROW 55001, ''Authenticated reviewer identity is required.'', 1;
    IF NOT EXISTS (
        SELECT 1 FROM dbo.FellowshipCallGroupGrant
        WHERE FellowshipCallId = @FellowshipCallId
          AND GroupName = @ActorGroup AND IsActive = 1
          AND AccessRole IN (''READ'',''ADMINISTER'')
    ) THROW 55002, ''The call is unavailable.'', 1;
    IF NOT EXISTS (
        SELECT 1 FROM dbo.FellowshipCall
        WHERE FellowshipCallId = @FellowshipCallId AND InternalSelectionStatus = ''OPEN''
    ) THROW 55003, ''Evaluation comments are closed for this call.'', 1;
    SELECT @EvaluatorId = FellowshipCallEvaluatorId
    FROM dbo.FellowshipCallEvaluator
    WHERE FellowshipCallId = @FellowshipCallId AND ActorEntraObjectId = @ActorEntraObjectId
      AND IsActive = 1;
    IF @EvaluatorId IS NULL THROW 55004, ''The signed-in identity is not an active evaluator.'', 1;
    IF NOT EXISTS (
        SELECT 1 FROM dbo.Application
        WHERE ApplicationId = @ApplicationId AND FellowshipCallId = @FellowshipCallId
    ) THROW 55005, ''The application is unavailable.'', 1;

    BEGIN TRY
        BEGIN TRANSACTION;
        SELECT @BeforeHasComment = CASE WHEN CommentText IS NULL THEN 0 ELSE 1 END
        FROM dbo.CallEvaluationSelection WITH (UPDLOCK, HOLDLOCK)
        WHERE FellowshipCallId = @FellowshipCallId AND ApplicationId = @ApplicationId
          AND FellowshipCallEvaluatorId = @EvaluatorId;

        IF @@ROWCOUNT = 0
            INSERT dbo.CallEvaluationSelection
                (FellowshipCallId, ApplicationId, FellowshipCallEvaluatorId,
                 GroupCode, ModifiedByIdentity, CommentText,
                 CommentModifiedByIdentity, CommentRecordedAtUtc)
            VALUES (@FellowshipCallId, @ApplicationId, @EvaluatorId,
                    NULL, @ActorIdentity, @AfterComment,
                    CASE WHEN @AfterComment IS NULL THEN NULL ELSE @ActorIdentity END,
                    CASE WHEN @AfterComment IS NULL THEN NULL ELSE SYSUTCDATETIME() END);
        ELSE
            UPDATE dbo.CallEvaluationSelection
            SET CommentText = @AfterComment,
                CommentModifiedByIdentity = CASE WHEN @AfterComment IS NULL THEN NULL ELSE @ActorIdentity END,
                CommentRecordedAtUtc = CASE WHEN @AfterComment IS NULL THEN NULL ELSE SYSUTCDATETIME() END
            WHERE FellowshipCallId = @FellowshipCallId AND ApplicationId = @ApplicationId
              AND FellowshipCallEvaluatorId = @EvaluatorId;

        SELECT @PayloadJson = (
            SELECT @BeforeHasComment AS hadComment,
                   CONVERT(bit, CASE WHEN @AfterComment IS NULL THEN 0 ELSE 1 END) AS hasComment
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        );
        INSERT dbo.AuditEvent
            (FellowshipCallId, ApplicationId, EventType, ActorIdentity,
             EntityType, EntityId, PayloadJson)
        VALUES
            (@FellowshipCallId, @ApplicationId, ''CALL_EVALUATION_COMMENT_SET'', @ActorIdentity,
             ''CallEvaluationSelection'', @ApplicationId, @PayloadJson);
        COMMIT TRANSACTION;
        SELECT @AfterComment AS CommentText;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

GRANT EXECUTE ON dbo.GetCallEvaluationOverview TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.SetCallEvaluationComment TO EHFApplicationRuntime;

/* Magda confirmed that every blank EHF-2026 assessment was a C. Preserve existing scores. */
DECLARE @CallId uniqueidentifier =
    (SELECT FellowshipCallId FROM dbo.FellowshipCall WHERE CallCode = N'EHF-2026');
IF @CallId IS NULL THROW 55006, 'The 2026 fellowship call is missing.', 1;
DECLARE @Changed TABLE (ApplicationId uniqueidentifier NOT NULL PRIMARY KEY);
DECLARE @Actor nvarchar(255) = N'admin:adriano-aguzzi';

BEGIN TRY
    BEGIN TRANSACTION;

    UPDATE old
       SET IsSelected = 1,
           GroupCode = 'C',
           ModifiedByIdentity = @Actor,
           RecordedAtUtc = SYSUTCDATETIME()
    OUTPUT inserted.ApplicationId INTO @Changed(ApplicationId)
    FROM dbo.TrusteeShortlistSelection AS old
    JOIN dbo.Application AS application_row ON application_row.ApplicationId = old.ApplicationId
    JOIN dbo.ShortlistTrustee AS trustee ON trustee.TrusteeCode = old.TrusteeCode
    WHERE application_row.FellowshipCallId = @CallId
      AND trustee.TrusteeCode = 'magda'
      AND old.GroupCode IS NULL;

    INSERT dbo.TrusteeShortlistSelection
        (ApplicationId, TrusteeCode, IsSelected, GroupCode, ModifiedByIdentity)
    OUTPUT inserted.ApplicationId INTO @Changed(ApplicationId)
    SELECT application_row.ApplicationId, 'magda', 1, 'C', @Actor
    FROM dbo.Application AS application_row
    WHERE application_row.FellowshipCallId = @CallId
      AND NOT EXISTS (
          SELECT 1 FROM dbo.TrusteeShortlistSelection AS existing
          WHERE existing.ApplicationId = application_row.ApplicationId
            AND existing.TrusteeCode = 'magda'
      );

    INSERT dbo.AuditEvent
        (FellowshipCallId, ApplicationId, EventType, ActorIdentity,
         EntityType, EntityId, PayloadJson)
    SELECT @CallId, changed.ApplicationId, 'SHORTLIST_SELECTION_SET', @Actor,
           'TrusteeShortlistSelection', changed.ApplicationId,
           N'{"reviewer":"Magda","value":"C","basis":"Magda confirmed blank scores were C; entered by Adriano Aguzzi on 2026-09-27."}'
    FROM @Changed AS changed;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
