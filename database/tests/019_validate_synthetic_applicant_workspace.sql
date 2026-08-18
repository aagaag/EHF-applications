SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.ApplicantSyntheticWorkspace', N'U') IS NULL
    THROW 53900, 'Synthetic applicant workspaces are missing.', 1;
IF OBJECT_ID(N'dbo.CreateSyntheticApplicantWorkspace', N'P') IS NULL
    THROW 53901, 'Synthetic applicant workspace creation is missing.', 1;
IF OBJECT_ID(N'dbo.GetApplicantSessionV19', N'P') IS NULL
    THROW 53902, 'Version-19 applicant sessions are missing.', 1;
IF COL_LENGTH(N'dbo.ApplicantSession', N'SyntheticActorIdentity') IS NULL
    THROW 53903, 'Synthetic applicant actor binding is missing.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND major_id = OBJECT_ID(N'dbo.CreateSyntheticApplicantWorkspace', N'P')
      AND permission_name = N'EXECUTE' AND state IN (N'G', N'W')
)
    THROW 53904, 'Runtime synthetic workspace execution is missing.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND major_id = OBJECT_ID(N'dbo.GetApplicantSessionV19', N'P')
      AND permission_name = N'EXECUTE' AND state IN (N'G', N'W')
)
    THROW 53912, 'Runtime version-19 session execution is missing.', 1;
IF EXISTS
(
    SELECT 1
    FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND major_id = OBJECT_ID(N'dbo.ApplicantSyntheticWorkspace', N'U')
      AND permission_name IN (N'SELECT', N'INSERT', N'UPDATE', N'DELETE')
      AND state IN (N'G', N'W')
)
    THROW 53913, 'Runtime synthetic workspace table access must remain denied.', 1;

DECLARE @IdleAt datetime2(7) = DATEADD(hour, 1, SYSUTCDATETIME()),
        @AbsoluteAt datetime2(7) = DATEADD(hour, 2, SYSUTCDATETIME());

-- Main positive phase.
BEGIN TRANSACTION;
DECLARE @SessionHash binary(32) = HASHBYTES('SHA2_256', N'019 synthetic session'),
        @CsrfHash binary(32) = HASHBYTES('SHA2_256', N'019 synthetic csrf'),
        @ApplicationId uniqueidentifier;
DECLARE @Created TABLE (ApplicationId uniqueidentifier NOT NULL);
INSERT @Created
EXEC dbo.CreateSyntheticApplicantWorkspace
    @ActorIdentity=N'validator-admin-a', @ActorGroup=N'EHF-Administrators',
    @SessionTokenSha256=@SessionHash, @CsrfTokenSha256=@CsrfHash,
    @IdleExpiresAtUtc=@IdleAt, @AbsoluteExpiresAtUtc=@AbsoluteAt;
SELECT @ApplicationId = ApplicationId FROM @Created;
IF @ApplicationId IS NULL
BEGIN
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53905, 'Synthetic workspace creation returned no server-generated application.', 1;
END;
IF NOT EXISTS
(
    SELECT 1
    FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
    JOIN dbo.Application AS application_row
      ON application_row.ApplicationId = workspace_row.ApplicationId
    JOIN dbo.ApplicantPortalBaseline AS baseline_row
      ON baseline_row.ApplicationId = workspace_row.ApplicationId
    JOIN dbo.ApplicantSession AS session_row
      ON session_row.ApplicationId = workspace_row.ApplicationId
    WHERE workspace_row.ApplicationId = @ApplicationId
      AND workspace_row.CreatedByIdentity = N'validator-admin-a'
      AND workspace_row.ClosedAtUtc IS NULL
      AND session_row.SyntheticActorIdentity = N'validator-admin-a'
      AND session_row.ApplicantInvitationId IS NULL
      AND session_row.EntraObjectId IS NULL
      AND application_row.ApplicationStatus = 'DRAFT'
      AND baseline_row.ProjectionJson = N'{"applicant":{"locked":false},"sections":{},"documents":[]}'
)
    THROW 53906, 'Synthetic workspace creation did not atomically bind neutral state.', 1;
IF NOT EXISTS
(
    SELECT 1 FROM dbo.AuditEvent
    WHERE ApplicationId = @ApplicationId
      AND EventType = 'SYNTHETIC_APPLICANT_WORKSPACE_CREATED'
      AND ActorIdentity = N'validator-admin-a'
)
    THROW 53907, 'Synthetic workspace creation was not auditable.', 1;

DECLARE @Legacy TABLE
(
    ApplicationId uniqueidentifier, CsrfTokenSha256 binary(32),
    IdleExpiresAtUtc datetime2(7), AbsoluteExpiresAtUtc datetime2(7),
    ApplicantInvitationId uniqueidentifier, EntraObjectId uniqueidentifier
);
INSERT @Legacy
EXEC dbo.GetApplicantSession @SessionTokenSha256=@SessionHash, @IdleExpiresAtUtc=@IdleAt;
IF EXISTS (SELECT 1 FROM @Legacy)
    THROW 53908, 'The legacy applicant session accepted a synthetic workspace.', 1;

DECLARE @V19 TABLE
(
    ApplicationId uniqueidentifier, CsrfTokenSha256 binary(32),
    IdleExpiresAtUtc datetime2(7), AbsoluteExpiresAtUtc datetime2(7),
    ApplicantInvitationId uniqueidentifier, EntraObjectId uniqueidentifier,
    SyntheticActorIdentity nvarchar(255)
);
INSERT @V19
EXEC dbo.GetApplicantSessionV19 @SessionTokenSha256=@SessionHash, @IdleExpiresAtUtc=@IdleAt;
IF NOT EXISTS
   (SELECT 1 FROM @V19
    WHERE ApplicationId=@ApplicationId AND SyntheticActorIdentity=N'validator-admin-a')
    THROW 53909, 'Version-19 session did not return its exact synthetic actor.', 1;

DECLARE @InvitationId uniqueidentifier = NEWID(),
        @NormalSessionHash binary(32) = HASHBYTES('SHA2_256', N'019 normal session'),
        @NormalCsrfHash binary(32) = HASHBYTES('SHA2_256', N'019 normal csrf'),
        @InvitationLastSeen datetime2(7);
INSERT dbo.ApplicantInvitation
    (ApplicantInvitationId, ApplicationId, InvitationTokenSha256, ExpiresAtUtc,
     CreatedByIdentity)
VALUES
    (@InvitationId, @ApplicationId, HASHBYTES('SHA2_256', N'019 normal invitation'),
     DATEADD(day, 1, SYSUTCDATETIME()), N'VALIDATOR');
INSERT dbo.ApplicantSession
    (ApplicantInvitationId, ApplicationId, EntraObjectId, SyntheticActorIdentity,
     SessionTokenSha256, CsrfTokenSha256, IdleExpiresAtUtc, AbsoluteExpiresAtUtc)
VALUES
    (@InvitationId, @ApplicationId, NULL, NULL, @NormalSessionHash,
     @NormalCsrfHash, @IdleAt, @AbsoluteAt);
SELECT @InvitationLastSeen = LastSeenAtUtc
FROM dbo.ApplicantSession
WHERE SessionTokenSha256 = @NormalSessionHash;
DELETE FROM @V19;
INSERT @V19
EXEC dbo.GetApplicantSessionV19
    @SessionTokenSha256=@NormalSessionHash, @IdleExpiresAtUtc=@IdleAt;
IF EXISTS (SELECT 1 FROM @V19)
    THROW 53915, 'A non-synthetic session opened a marked synthetic workspace.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM dbo.ApplicantSession
    WHERE SessionTokenSha256 = @NormalSessionHash
      AND LastSeenAtUtc = @InvitationLastSeen
)
    THROW 53926, 'A marker-backed invitation session updated LastSeenAtUtc.', 1;

DECLARE @EntraObjectId uniqueidentifier = NEWID(),
        @EntraSessionHash binary(32) = HASHBYTES('SHA2_256', N'019 Entra session'),
        @EntraCsrfHash binary(32) = HASHBYTES('SHA2_256', N'019 Entra csrf'),
        @EntraLastSeen datetime2(7);
INSERT dbo.ApplicantEntraIdentity
    (ApplicationId, EntraObjectId, ApplicantAccessRequestId, IdentityKind,
     Enabled, LinkedByIdentity)
VALUES
    (@ApplicationId, @EntraObjectId, NULL, 'SYNTHETIC_TEST', 1, N'VALIDATOR');
INSERT dbo.ApplicantSession
    (ApplicantInvitationId, ApplicationId, EntraObjectId, SyntheticActorIdentity,
     SessionTokenSha256, CsrfTokenSha256, IdleExpiresAtUtc, AbsoluteExpiresAtUtc)
VALUES
    (NULL, @ApplicationId, @EntraObjectId, NULL, @EntraSessionHash,
     @EntraCsrfHash, @IdleAt, @AbsoluteAt);
SELECT @EntraLastSeen = LastSeenAtUtc
FROM dbo.ApplicantSession
WHERE SessionTokenSha256 = @EntraSessionHash;
DELETE FROM @V19;
INSERT @V19
EXEC dbo.GetApplicantSessionV19
    @SessionTokenSha256=@EntraSessionHash, @IdleExpiresAtUtc=@IdleAt;
IF EXISTS (SELECT 1 FROM @V19)
    THROW 53927, 'A non-synthetic Entra session opened a marked synthetic workspace.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM dbo.ApplicantSession
    WHERE SessionTokenSha256 = @EntraSessionHash
      AND LastSeenAtUtc = @EntraLastSeen
)
    THROW 53928, 'A marker-backed Entra session updated LastSeenAtUtc.', 1;

DECLARE @RuntimeCreated TABLE (ApplicationId uniqueidentifier NOT NULL);
DECLARE @RuntimeApplicationId uniqueidentifier;
DECLARE @RuntimeSessionHash binary(32) = HASHBYTES('SHA2_256', N'019 runtime session'),
        @RuntimeCsrfHash binary(32) = HASHBYTES('SHA2_256', N'019 runtime csrf');
EXECUTE AS USER = N'ehf_app';
INSERT @RuntimeCreated
EXEC dbo.CreateSyntheticApplicantWorkspace
    @ActorIdentity=N'validator-runtime-admin', @ActorGroup=N'EHF-Administrators',
    @SessionTokenSha256=@RuntimeSessionHash,
    @CsrfTokenSha256=@RuntimeCsrfHash,
    @IdleExpiresAtUtc=@IdleAt, @AbsoluteExpiresAtUtc=@AbsoluteAt;
REVERT;
SELECT @RuntimeApplicationId = ApplicationId FROM @RuntimeCreated;
IF @RuntimeApplicationId IS NULL
BEGIN
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53916, 'Runtime execution could not create a synthetic workspace.', 1;
END;

DECLARE @MetricCallId uniqueidentifier;
SELECT @MetricCallId = FellowshipCallId
FROM dbo.FellowshipCall WITH (UPDLOCK, HOLDLOCK)
WHERE CallCode = N'EHF-2026';
IF @MetricCallId IS NULL
BEGIN
    SET @MetricCallId = NEWID();
    INSERT dbo.FellowshipCall
        (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
    VALUES
        (@MetricCallId, N'EHF-2026', N'Validator metrics call', 'DRAFT',
         DATEADD(day, 1, SYSUTCDATETIME()));
END;
UPDATE dbo.Application SET FellowshipCallId = @MetricCallId WHERE ApplicationId = @ApplicationId;

DECLARE @Previews TABLE
(
    ApplicationId uniqueidentifier, ApplicantName nvarchar(401), ApplicationStatus varchar(20)
);
DECLARE @Metrics TABLE
(
    ApplicantName nvarchar(401), Degree nvarchar(200), AgeObservation decimal(8,2),
    AcademicAgeObservation decimal(8,2), SelfReportedGender nvarchar(100),
    FirstAuthorPaperCount int, LastAuthorPaperCount int, TotalPaperCount int, HIndex int,
    TotalCitations bigint, Orcid nvarchar(200), GoogleScholarCitationCount bigint,
    IdentityCertainty nvarchar(200)
);
EXECUTE AS USER = N'ehf_app';
INSERT @Previews EXEC dbo.ListApplicantPreviews @ActorGroup=N'EHF-Administrators';
INSERT @Metrics EXEC dbo.GetInternalApplicationMetrics @ActorGroup=N'EHF-Administrators';
REVERT;
IF EXISTS (SELECT 1 FROM @Previews WHERE ApplicationId = @ApplicationId)
    THROW 53918, 'Synthetic workspace appeared in applicant previews.', 1;
IF EXISTS (SELECT 1 FROM @Metrics WHERE ApplicantName = N'Synthetic Applicant')
    THROW 53919, 'Synthetic workspace appeared in internal metrics.', 1;

DECLARE @MainManifestJson nvarchar(max) = N'{}',
        @MainManifestHash binary(32) = HASHBYTES('SHA2_256', CONVERT(varbinary(max), N'{}')),
        @MainFinalConfirmationId uniqueidentifier = NEWID();
INSERT dbo.ApplicantFinalConfirmation
    (ApplicantFinalConfirmationId, ApplicationId, ManifestJson, ManifestSha256,
     ConfirmedByIdentity)
VALUES
    (@MainFinalConfirmationId, @ApplicationId, @MainManifestJson, @MainManifestHash,
     N'VALIDATOR');
DECLARE @MainPending TABLE
(
    ApplicantFinalConfirmationId uniqueidentifier, ApplicationId uniqueidentifier,
    ConfirmedAtUtc datetime2(7)
);
EXECUTE AS USER = N'ehf_app';
INSERT @MainPending EXEC dbo.ListPendingApplicantSubmissions;
REVERT;
IF EXISTS (SELECT 1 FROM @MainPending WHERE ApplicantFinalConfirmationId = @MainFinalConfirmationId)
    THROW 53923, 'Synthetic workspace entered the approval queue.', 1;

UPDATE dbo.ApplicantSyntheticWorkspace
SET ClosedAtUtc = SYSUTCDATETIME()
WHERE ApplicationId = @ApplicationId;
DELETE FROM @V19;
INSERT @V19
EXEC dbo.GetApplicantSessionV19 @SessionTokenSha256=@SessionHash, @IdleExpiresAtUtc=@IdleAt;
IF EXISTS (SELECT 1 FROM @V19)
    THROW 53911, 'A closed synthetic workspace retained a session.', 1;
ROLLBACK TRANSACTION;

-- Expected denial phases.
-- Nonmember creation denial phase.
DECLARE @NonmemberDenied bit = 0,
        @NonmemberSessionHash binary(32) = HASHBYTES('SHA2_256', N'019 nonmember session'),
        @NonmemberCsrfHash binary(32) = HASHBYTES('SHA2_256', N'019 nonmember csrf');
BEGIN TRANSACTION;
BEGIN TRY
    EXEC dbo.CreateSyntheticApplicantWorkspace
        @ActorIdentity=N'validator-nonmember', @ActorGroup=N'EHF-Trustees',
        @SessionTokenSha256=@NonmemberSessionHash,
        @CsrfTokenSha256=@NonmemberCsrfHash,
        @IdleExpiresAtUtc=@IdleAt, @AbsoluteExpiresAtUtc=@AbsoluteAt;
END TRY
BEGIN CATCH
    DECLARE @NonmemberError int = ERROR_NUMBER();
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    IF @NonmemberError <> 52900 THROW;
    SET @NonmemberDenied = 1;
END CATCH;
IF @NonmemberDenied = 0
BEGIN
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53910, 'A non-administrator created a synthetic workspace.', 1;
END;

-- Null-group creation denial phase.
DECLARE @NullGroupDenied bit = 0,
        @NullGroupSessionHash binary(32) = HASHBYTES('SHA2_256', N'019 null group session'),
        @NullGroupCsrfHash binary(32) = HASHBYTES('SHA2_256', N'019 null group csrf');
BEGIN TRANSACTION;
BEGIN TRY
    EXEC dbo.CreateSyntheticApplicantWorkspace
        @ActorIdentity=N'validator-null-group', @ActorGroup=NULL,
        @SessionTokenSha256=@NullGroupSessionHash,
        @CsrfTokenSha256=@NullGroupCsrfHash,
        @IdleExpiresAtUtc=@IdleAt, @AbsoluteExpiresAtUtc=@AbsoluteAt;
END TRY
BEGIN CATCH
    DECLARE @NullGroupError int = ERROR_NUMBER();
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    IF @NullGroupError <> 52900 THROW;
    SET @NullGroupDenied = 1;
END CATCH;
IF @NullGroupDenied = 0
BEGIN
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53914, 'A NULL administrator group created a synthetic workspace.', 1;
END;

-- Runtime direct-DML denial phase.
DECLARE @RuntimeDirectDenied bit = 0;
BEGIN TRANSACTION;
EXECUTE AS USER = N'ehf_app';
BEGIN TRY
    SELECT TOP (1) ApplicationId FROM dbo.ApplicantSyntheticWorkspace;
END TRY
BEGIN CATCH
    DECLARE @RuntimeDirectError int = ERROR_NUMBER();
    REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    IF @RuntimeDirectError <> 229 THROW;
    SET @RuntimeDirectDenied = 1;
END CATCH;
IF @RuntimeDirectDenied = 0
BEGIN
    REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53917, 'Runtime directly read the synthetic workspace marker.', 1;
END;

-- Preview denial phase.
DECLARE @PreviewDenied bit = 0,
        @PreviewSessionHash binary(32) = HASHBYTES('SHA2_256', N'019 preview session'),
        @PreviewCsrfHash binary(32) = HASHBYTES('SHA2_256', N'019 preview csrf'),
        @PreviewApplicationId uniqueidentifier;
DECLARE @PreviewCreated TABLE (ApplicationId uniqueidentifier NOT NULL);
BEGIN TRANSACTION;
INSERT @PreviewCreated
EXEC dbo.CreateSyntheticApplicantWorkspace
    @ActorIdentity=N'validator-preview-admin', @ActorGroup=N'EHF-Administrators',
    @SessionTokenSha256=@PreviewSessionHash, @CsrfTokenSha256=@PreviewCsrfHash,
    @IdleExpiresAtUtc=@IdleAt, @AbsoluteExpiresAtUtc=@AbsoluteAt;
SELECT @PreviewApplicationId = ApplicationId FROM @PreviewCreated;
IF @PreviewApplicationId IS NULL
BEGIN
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53905, 'Preview denial fixture creation failed.', 1;
END;
EXECUTE AS USER = N'ehf_app';
BEGIN TRY
    EXEC dbo.GetApplicantPreview
        @ApplicationId=@PreviewApplicationId, @ActorIdentity=N'validator-runtime-admin',
        @ActorGroup=N'EHF-Administrators', @EmitResult=0, @EmitDrafts=0;
END TRY
BEGIN CATCH
    DECLARE @PreviewError int = ERROR_NUMBER();
    REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    IF @PreviewError <> 52910 THROW;
    SET @PreviewDenied = 1;
END CATCH;
IF @PreviewDenied = 0
BEGIN
    REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53920, 'Synthetic workspace opened in applicant preview.', 1;
END;

-- Provision denial phase.
DECLARE @ProvisionDenied bit = 0,
        @ProvisionSessionHash binary(32) = HASHBYTES('SHA2_256', N'019 provision session'),
        @ProvisionCsrfHash binary(32) = HASHBYTES('SHA2_256', N'019 provision csrf'),
        @ProvisionApplicationId uniqueidentifier,
        @AccessRequestId uniqueidentifier = NEWID(),
        @ProvisioningEntraObjectId uniqueidentifier = NEWID();
DECLARE @ProvisionCreated TABLE (ApplicationId uniqueidentifier NOT NULL);
BEGIN TRANSACTION;
INSERT @ProvisionCreated
EXEC dbo.CreateSyntheticApplicantWorkspace
    @ActorIdentity=N'validator-provision-admin', @ActorGroup=N'EHF-Administrators',
    @SessionTokenSha256=@ProvisionSessionHash, @CsrfTokenSha256=@ProvisionCsrfHash,
    @IdleExpiresAtUtc=@IdleAt, @AbsoluteExpiresAtUtc=@AbsoluteAt;
SELECT @ProvisionApplicationId = ApplicationId FROM @ProvisionCreated;
IF @ProvisionApplicationId IS NULL
BEGIN
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53905, 'Provision denial fixture creation failed.', 1;
END;
INSERT dbo.ApplicantAccessRequest
    (ApplicantAccessRequestId, RequestedEmail, RequestedDisplayName, RequestStatus,
     ReviewedByIdentity, ReviewerGroup, ReviewedAtUtc)
VALUES
    (@AccessRequestId, N'synthetic-provision@example.test', N'Synthetic workspace',
     'APPROVED', N'VALIDATOR', 'EHF-Administrators', SYSUTCDATETIME());
EXECUTE AS USER = N'ehf_app';
BEGIN TRY
    EXEC dbo.ProvisionApplicantAccessRequest
        @ApplicantAccessRequestId=@AccessRequestId, @ApplicationId=@ProvisionApplicationId,
        @EntraObjectId=@ProvisioningEntraObjectId,
        @ProvisionedByIdentity=N'validator-runtime-admin',
        @ProvisionerGroup='EHF-Administrators';
END TRY
BEGIN CATCH
    DECLARE @ProvisionError int = ERROR_NUMBER();
    REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    IF @ProvisionError <> 52911 THROW;
    SET @ProvisionDenied = 1;
END CATCH;
IF @ProvisionDenied = 0
BEGIN
    REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53921, 'Synthetic workspace received an Entra applicant identity.', 1;
END;

-- Final submission denial phase.
DECLARE @SubmissionDenied bit = 0,
        @SubmissionSessionHash binary(32) = HASHBYTES('SHA2_256', N'019 submission session'),
        @SubmissionCsrfHash binary(32) = HASHBYTES('SHA2_256', N'019 submission csrf'),
        @SubmissionApplicationId uniqueidentifier,
        @SubmissionManifestJson nvarchar(max) = N'{}',
        @SubmissionManifestHash binary(32) = HASHBYTES('SHA2_256', CONVERT(varbinary(max), N'{}'));
DECLARE @SubmissionCreated TABLE (ApplicationId uniqueidentifier NOT NULL);
BEGIN TRANSACTION;
INSERT @SubmissionCreated
EXEC dbo.CreateSyntheticApplicantWorkspace
    @ActorIdentity=N'validator-submission-admin', @ActorGroup=N'EHF-Administrators',
    @SessionTokenSha256=@SubmissionSessionHash, @CsrfTokenSha256=@SubmissionCsrfHash,
    @IdleExpiresAtUtc=@IdleAt, @AbsoluteExpiresAtUtc=@AbsoluteAt;
SELECT @SubmissionApplicationId = ApplicationId FROM @SubmissionCreated;
IF @SubmissionApplicationId IS NULL
BEGIN
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53905, 'Final-submission denial fixture creation failed.', 1;
END;
EXECUTE AS USER = N'ehf_app';
BEGIN TRY
    EXEC dbo.SubmitApplicantFinalConfirmation
        @SessionTokenSha256=@SubmissionSessionHash,
        @ManifestJson=@SubmissionManifestJson,
        @ManifestSha256=@SubmissionManifestHash;
END TRY
BEGIN CATCH
    DECLARE @SubmissionError int = ERROR_NUMBER();
    REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    IF @SubmissionError <> 52913 THROW;
    SET @SubmissionDenied = 1;
END CATCH;
IF @SubmissionDenied = 0
BEGIN
    REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53922, 'Synthetic workspace submitted a final confirmation.', 1;
END;

-- Submission review denial phase.
DECLARE @ReviewDenied bit = 0,
        @ReviewSessionHash binary(32) = HASHBYTES('SHA2_256', N'019 review session'),
        @ReviewCsrfHash binary(32) = HASHBYTES('SHA2_256', N'019 review csrf'),
        @ReviewApplicationId uniqueidentifier,
        @ReviewManifestJson nvarchar(max) = N'{}',
        @ReviewManifestHash binary(32) = HASHBYTES('SHA2_256', CONVERT(varbinary(max), N'{}')),
        @ReviewFinalConfirmationId uniqueidentifier = NEWID();
DECLARE @ReviewCreated TABLE (ApplicationId uniqueidentifier NOT NULL);
BEGIN TRANSACTION;
INSERT @ReviewCreated
EXEC dbo.CreateSyntheticApplicantWorkspace
    @ActorIdentity=N'validator-review-admin', @ActorGroup=N'EHF-Administrators',
    @SessionTokenSha256=@ReviewSessionHash, @CsrfTokenSha256=@ReviewCsrfHash,
    @IdleExpiresAtUtc=@IdleAt, @AbsoluteExpiresAtUtc=@AbsoluteAt;
SELECT @ReviewApplicationId = ApplicationId FROM @ReviewCreated;
IF @ReviewApplicationId IS NULL
BEGIN
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53905, 'Submission-review denial fixture creation failed.', 1;
END;
INSERT dbo.ApplicantFinalConfirmation
    (ApplicantFinalConfirmationId, ApplicationId, ManifestJson, ManifestSha256,
     ConfirmedByIdentity)
VALUES
    (@ReviewFinalConfirmationId, @ReviewApplicationId, @ReviewManifestJson,
     @ReviewManifestHash, N'VALIDATOR');
EXECUTE AS USER = N'ehf_app';
BEGIN TRY
    EXEC dbo.GetApplicantSubmissionReview
        @ApplicantFinalConfirmationId=@ReviewFinalConfirmationId;
END TRY
BEGIN CATCH
    DECLARE @ReviewError int = ERROR_NUMBER();
    REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    IF @ReviewError <> 52914 THROW;
    SET @ReviewDenied = 1;
END CATCH;
IF @ReviewDenied = 0
BEGIN
    REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53924, 'Synthetic workspace opened in submission review.', 1;
END;

-- Approval denial phase.
DECLARE @ApprovalDenied bit = 0,
        @ApprovalSessionHash binary(32) = HASHBYTES('SHA2_256', N'019 approval session'),
        @ApprovalCsrfHash binary(32) = HASHBYTES('SHA2_256', N'019 approval csrf'),
        @ApprovalApplicationId uniqueidentifier,
        @ApprovalManifestJson nvarchar(max) = N'{}',
        @ApprovalManifestHash binary(32) = HASHBYTES('SHA2_256', CONVERT(varbinary(max), N'{}')),
        @ApprovalFinalConfirmationId uniqueidentifier = NEWID();
DECLARE @ApprovalCreated TABLE (ApplicationId uniqueidentifier NOT NULL);
BEGIN TRANSACTION;
INSERT @ApprovalCreated
EXEC dbo.CreateSyntheticApplicantWorkspace
    @ActorIdentity=N'validator-approval-admin', @ActorGroup=N'EHF-Administrators',
    @SessionTokenSha256=@ApprovalSessionHash, @CsrfTokenSha256=@ApprovalCsrfHash,
    @IdleExpiresAtUtc=@IdleAt, @AbsoluteExpiresAtUtc=@AbsoluteAt;
SELECT @ApprovalApplicationId = ApplicationId FROM @ApprovalCreated;
IF @ApprovalApplicationId IS NULL
BEGIN
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53905, 'Approval denial fixture creation failed.', 1;
END;
INSERT dbo.ApplicantFinalConfirmation
    (ApplicantFinalConfirmationId, ApplicationId, ManifestJson, ManifestSha256,
     ConfirmedByIdentity)
VALUES
    (@ApprovalFinalConfirmationId, @ApprovalApplicationId, @ApprovalManifestJson,
     @ApprovalManifestHash, N'VALIDATOR');
EXECUTE AS USER = N'ehf_app';
BEGIN TRY
    EXEC dbo.ApproveApplicantSubmission
        @ApplicantFinalConfirmationId=@ApprovalFinalConfirmationId,
        @ReviewedByIdentity=N'validator-runtime-admin', @ReviewerGroup='EHF-Administrators';
END TRY
BEGIN CATCH
    DECLARE @ApprovalError int = ERROR_NUMBER();
    REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    IF @ApprovalError <> 52912 THROW;
    SET @ApprovalDenied = 1;
END CATCH;
IF @ApprovalDenied = 0
BEGIN
    REVERT;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW 53925, 'Synthetic workspace entered approval.', 1;
END;

IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
PRINT 'PASS 019 synthetic applicant workspace';
