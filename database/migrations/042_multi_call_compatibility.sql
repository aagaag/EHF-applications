SET NOCOUNT ON;
SET XACT_ABORT ON;

/* Keep the already-applied multi-call migration immutable.  This follow-on
   migration makes legacy fixture and synthetic-workspace creation explicitly
   call-aware, rather than relying on an omitted NOT NULL column. */
BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.DF_FellowshipCall_PublicSlug', N'D') IS NULL
    ALTER TABLE dbo.FellowshipCall ADD
        CONSTRAINT DF_FellowshipCall_PublicSlug
        DEFAULT (LOWER(CONVERT(varchar(36), NEWID()))) FOR PublicSlug;
IF OBJECT_ID(N'dbo.DF_FellowshipCall_CompactTitle', N'D') IS NULL
    ALTER TABLE dbo.FellowshipCall ADD
        CONSTRAINT DF_FellowshipCall_CompactTitle
        DEFAULT N'Untitled fellowship call' FOR CompactTitle;
IF OBJECT_ID(N'dbo.DF_FellowshipCall_ApplicantReviewStatus', N'D') IS NULL
    ALTER TABLE dbo.FellowshipCall ADD
        CONSTRAINT DF_FellowshipCall_ApplicantReviewStatus
        DEFAULT 'DISABLED' FOR ApplicantReviewStatus;
IF OBJECT_ID(N'dbo.DF_FellowshipCall_InternalSelectionStatus', N'D') IS NULL
    ALTER TABLE dbo.FellowshipCall ADD
        CONSTRAINT DF_FellowshipCall_InternalSelectionStatus
        DEFAULT 'DISABLED' FOR InternalSelectionStatus;
IF OBJECT_ID(N'dbo.DF_FellowshipCall_InvitationsEnabled', N'D') IS NULL
    ALTER TABLE dbo.FellowshipCall ADD
        CONSTRAINT DF_FellowshipCall_InvitationsEnabled DEFAULT 0 FOR InvitationsEnabled;
IF OBJECT_ID(N'dbo.DF_FellowshipCall_AnalysisProfileCode', N'D') IS NULL
    ALTER TABLE dbo.FellowshipCall ADD
        CONSTRAINT DF_FellowshipCall_AnalysisProfileCode
        DEFAULT 'ehf-standard-v1' FOR AnalysisProfileCode;

ALTER TABLE dbo.Application DROP CONSTRAINT FK_Application_CallApplicant;
ALTER TABLE dbo.Application ADD
    CONSTRAINT FK_Application_CallApplicant FOREIGN KEY (FellowshipCallId, ApplicantId)
        REFERENCES dbo.Applicant (FellowshipCallId, ApplicantId)
        ON UPDATE CASCADE;

COMMIT TRANSACTION;

EXEC(N'
ALTER PROCEDURE dbo.CreateSyntheticApplicantWorkspace
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128),
    @SessionTokenSha256 binary(32),
    @CsrfTokenSha256 binary(32),
    @IdleExpiresAtUtc datetime2(7),
    @AbsoluteExpiresAtUtc datetime2(7)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    SET @ActorIdentity = LTRIM(RTRIM(@ActorIdentity));
    IF @ActorGroup IS NULL OR @ActorGroup <> N''EHF-Administrators''
       OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
        THROW 52900, ''Administrator authorization is required.'', 1;
    IF @IdleExpiresAtUtc <= SYSUTCDATETIME()
       OR @AbsoluteExpiresAtUtc < @IdleExpiresAtUtc
        THROW 52901, ''Synthetic session expiry is invalid.'', 1;

    DECLARE @CallId uniqueidentifier,
            @ApplicantId uniqueidentifier = NEWID(),
            @WorkspaceApplicationId uniqueidentifier = NEWID();

    BEGIN TRANSACTION;
    BEGIN TRY
        SELECT @CallId = FellowshipCallId
        FROM dbo.FellowshipCall WITH (UPDLOCK, HOLDLOCK)
        WHERE CallCode = N''EHF-SYNTHETIC-WORKSPACE'';
        IF @CallId IS NULL
        BEGIN
            SET @CallId = NEWID();
            INSERT dbo.FellowshipCall
                (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
            VALUES
                (@CallId, N''EHF-SYNTHETIC-WORKSPACE'', N''Synthetic applicant workspace'',
                 ''DRAFT'', DATEADD(day, 1, SYSUTCDATETIME()));
        END;

        INSERT dbo.Applicant
            (ApplicantId, FellowshipCallId, LegalGivenNames, LegalFamilyName, SelfReportedGender)
        VALUES
            (@ApplicantId, @CallId, N''Synthetic'', N''Applicant'', N''Prefer not to say'');
        INSERT dbo.Application
            (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus)
        VALUES
            (@WorkspaceApplicationId, @CallId, @ApplicantId, ''DRAFT'');
        INSERT dbo.ApplicantPortalBaseline
            (ApplicationId, ProjectionJson, CreatedByIdentity)
        VALUES
            (@WorkspaceApplicationId,
             N''{"applicant":{"locked":false},"sections":{},"documents":[]}'',
             @ActorIdentity);
        INSERT dbo.ApplicantSyntheticWorkspace
            (ApplicationId, CreatedByIdentity)
        VALUES
            (@WorkspaceApplicationId, @ActorIdentity);
        INSERT dbo.ApplicantSession
            (ApplicantInvitationId, ApplicationId, EntraObjectId, SyntheticActorIdentity,
             SessionTokenSha256, CsrfTokenSha256, IdleExpiresAtUtc, AbsoluteExpiresAtUtc)
        VALUES
            (NULL, @WorkspaceApplicationId, NULL, @ActorIdentity,
             @SessionTokenSha256, @CsrfTokenSha256, @IdleExpiresAtUtc, @AbsoluteExpiresAtUtc);
        INSERT dbo.AuditEvent
            (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
        VALUES
            (@WorkspaceApplicationId, ''SYNTHETIC_APPLICANT_WORKSPACE_CREATED'',
             @ActorIdentity, ''Application'', @WorkspaceApplicationId,
             (SELECT @WorkspaceApplicationId AS applicationId
              FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;

    SELECT @WorkspaceApplicationId AS ApplicationId;
END;
');

PRINT 'PASS 042 multi-call compatibility';
