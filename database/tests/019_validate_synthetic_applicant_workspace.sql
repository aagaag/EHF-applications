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

BEGIN TRANSACTION;
DECLARE @SessionHash binary(32) = HASHBYTES('SHA2_256', N'019 synthetic session'),
        @CsrfHash binary(32) = HASHBYTES('SHA2_256', N'019 synthetic csrf'),
        @IdleAt datetime2(7) = DATEADD(hour, 1, SYSUTCDATETIME()),
        @AbsoluteAt datetime2(7) = DATEADD(hour, 2, SYSUTCDATETIME()),
        @ApplicationId uniqueidentifier;
DECLARE @Created TABLE (ApplicationId uniqueidentifier NOT NULL);
INSERT @Created
EXEC dbo.CreateSyntheticApplicantWorkspace
    @ActorIdentity=N'validator-admin-a', @ActorGroup=N'EHF-Administrators',
    @SessionTokenSha256=@SessionHash, @CsrfTokenSha256=@CsrfHash,
    @IdleExpiresAtUtc=@IdleAt, @AbsoluteExpiresAtUtc=@AbsoluteAt;
SELECT @ApplicationId = ApplicationId FROM @Created;
IF @ApplicationId IS NULL
    THROW 53905, 'Synthetic workspace creation returned no server-generated application.', 1;
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

DECLARE @Denied bit = 0;
BEGIN TRY
    EXEC dbo.CreateSyntheticApplicantWorkspace
        @ActorIdentity=N'validator-nonmember', @ActorGroup=N'EHF-Trustees',
        @SessionTokenSha256=HASHBYTES('SHA2_256', N'019 nonmember session'),
        @CsrfTokenSha256=HASHBYTES('SHA2_256', N'019 nonmember csrf'),
        @IdleExpiresAtUtc=@IdleAt, @AbsoluteExpiresAtUtc=@AbsoluteAt;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() <> 52900 THROW;
    SET @Denied = 1;
END CATCH;
IF @Denied = 0
    THROW 53910, 'A non-administrator created a synthetic workspace.', 1;

SET @Denied = 0;
BEGIN TRY
    EXEC dbo.CreateSyntheticApplicantWorkspace
        @ActorIdentity=N'validator-null-group', @ActorGroup=NULL,
        @SessionTokenSha256=HASHBYTES('SHA2_256', N'019 null group session'),
        @CsrfTokenSha256=HASHBYTES('SHA2_256', N'019 null group csrf'),
        @IdleExpiresAtUtc=@IdleAt, @AbsoluteExpiresAtUtc=@AbsoluteAt;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() <> 52900 THROW;
    SET @Denied = 1;
END CATCH;
IF @Denied = 0
    THROW 53914, 'A NULL administrator group created a synthetic workspace.', 1;

DECLARE @InvitationId uniqueidentifier = NEWID(),
        @NormalSessionHash binary(32) = HASHBYTES('SHA2_256', N'019 normal session'),
        @NormalCsrfHash binary(32) = HASHBYTES('SHA2_256', N'019 normal csrf');
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
DELETE FROM @V19;
INSERT @V19
EXEC dbo.GetApplicantSessionV19
    @SessionTokenSha256=@NormalSessionHash, @IdleExpiresAtUtc=@IdleAt;
IF EXISTS (SELECT 1 FROM @V19)
    THROW 53915, 'A non-synthetic session opened a marked synthetic workspace.', 1;

DECLARE @RuntimeCreated TABLE (ApplicationId uniqueidentifier NOT NULL),
        @RuntimeApplicationId uniqueidentifier;
EXECUTE AS USER = N'ehf_app';
INSERT @RuntimeCreated
EXEC dbo.CreateSyntheticApplicantWorkspace
    @ActorIdentity=N'validator-runtime-admin', @ActorGroup=N'EHF-Administrators',
    @SessionTokenSha256=HASHBYTES('SHA2_256', N'019 runtime session'),
    @CsrfTokenSha256=HASHBYTES('SHA2_256', N'019 runtime csrf'),
    @IdleExpiresAtUtc=@IdleAt, @AbsoluteExpiresAtUtc=@AbsoluteAt;
REVERT;
SELECT @RuntimeApplicationId = ApplicationId FROM @RuntimeCreated;
IF @RuntimeApplicationId IS NULL
    THROW 53916, 'Runtime execution could not create a synthetic workspace.', 1;

DECLARE @RuntimeDirectDenied bit = 0;
EXECUTE AS USER = N'ehf_app';
BEGIN TRY
    SELECT TOP (1) ApplicationId FROM dbo.ApplicantSyntheticWorkspace;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() <> 229
    BEGIN
        REVERT;
        THROW;
    END;
    SET @RuntimeDirectDenied = 1;
END CATCH;
REVERT;
IF @RuntimeDirectDenied = 0
    THROW 53917, 'Runtime directly read the synthetic workspace marker.', 1;

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

SET @Denied = 0;
EXECUTE AS USER = N'ehf_app';
BEGIN TRY
    EXEC dbo.GetApplicantPreview
        @ApplicationId=@ApplicationId, @ActorIdentity=N'validator-runtime-admin',
        @ActorGroup=N'EHF-Administrators', @EmitResult=0, @EmitDrafts=0;
END TRY
BEGIN CATCH
    DECLARE @PreviewError int = ERROR_NUMBER();
    REVERT;
    IF @PreviewError <> 52910 THROW;
    SET @Denied = 1;
END CATCH;
IF @Denied = 0
BEGIN
    REVERT;
    THROW 53920, 'Synthetic workspace opened in applicant preview.', 1;
END;

DECLARE @AccessRequestId uniqueidentifier = NEWID();
INSERT dbo.ApplicantAccessRequest
    (ApplicantAccessRequestId, RequestedEmail, RequestedDisplayName, RequestStatus,
     ReviewedByIdentity, ReviewerGroup, ReviewedAtUtc)
VALUES
    (@AccessRequestId, N'synthetic-workspace@example.test', N'Synthetic workspace',
     'APPROVED', N'VALIDATOR', 'EHF-Administrators', SYSUTCDATETIME());
SET @Denied = 0;
EXECUTE AS USER = N'ehf_app';
BEGIN TRY
    EXEC dbo.ProvisionApplicantAccessRequest
        @ApplicantAccessRequestId=@AccessRequestId, @ApplicationId=@ApplicationId,
        @EntraObjectId=NEWID(), @ProvisionedByIdentity=N'validator-runtime-admin',
        @ProvisionerGroup='EHF-Administrators';
END TRY
BEGIN CATCH
    DECLARE @ProvisionError int = ERROR_NUMBER();
    REVERT;
    IF @ProvisionError <> 52911 THROW;
    SET @Denied = 1;
END CATCH;
IF @Denied = 0
BEGIN
    REVERT;
    THROW 53921, 'Synthetic workspace received an Entra applicant identity.', 1;
END;

DECLARE @ManifestJson nvarchar(max) = N'{}',
        @ManifestHash binary(32) = HASHBYTES('SHA2_256', CONVERT(varbinary(max), N'{}')),
        @FinalConfirmationId uniqueidentifier = NEWID();
SET @Denied = 0;
EXECUTE AS USER = N'ehf_app';
BEGIN TRY
    EXEC dbo.SubmitApplicantFinalConfirmation
        @SessionTokenSha256=@SessionHash, @ManifestJson=@ManifestJson,
        @ManifestSha256=@ManifestHash;
END TRY
BEGIN CATCH
    DECLARE @SubmissionError int = ERROR_NUMBER();
    REVERT;
    IF @SubmissionError <> 52913 THROW;
    SET @Denied = 1;
END CATCH;
IF @Denied = 0
BEGIN
    REVERT;
    THROW 53922, 'Synthetic workspace submitted a final confirmation.', 1;
END;

INSERT dbo.ApplicantFinalConfirmation
    (ApplicantFinalConfirmationId, ApplicationId, ManifestJson, ManifestSha256,
     ConfirmedByIdentity)
VALUES
    (@FinalConfirmationId, @ApplicationId, @ManifestJson, @ManifestHash, N'VALIDATOR');
DECLARE @Pending TABLE
(
    ApplicantFinalConfirmationId uniqueidentifier, ApplicationId uniqueidentifier,
    ConfirmedAtUtc datetime2(7)
);
EXECUTE AS USER = N'ehf_app';
INSERT @Pending EXEC dbo.ListPendingApplicantSubmissions;
REVERT;
IF EXISTS (SELECT 1 FROM @Pending WHERE ApplicantFinalConfirmationId = @FinalConfirmationId)
    THROW 53923, 'Synthetic workspace entered the approval queue.', 1;

SET @Denied = 0;
EXECUTE AS USER = N'ehf_app';
BEGIN TRY
    EXEC dbo.GetApplicantSubmissionReview @ApplicantFinalConfirmationId=@FinalConfirmationId;
END TRY
BEGIN CATCH
    DECLARE @ReviewError int = ERROR_NUMBER();
    REVERT;
    IF @ReviewError <> 52914 THROW;
    SET @Denied = 1;
END CATCH;
IF @Denied = 0
BEGIN
    REVERT;
    THROW 53924, 'Synthetic workspace opened in submission review.', 1;
END;

SET @Denied = 0;
EXECUTE AS USER = N'ehf_app';
BEGIN TRY
    EXEC dbo.ApproveApplicantSubmission
        @ApplicantFinalConfirmationId=@FinalConfirmationId,
        @ReviewedByIdentity=N'validator-runtime-admin', @ReviewerGroup='EHF-Administrators';
END TRY
BEGIN CATCH
    DECLARE @ApprovalError int = ERROR_NUMBER();
    REVERT;
    IF @ApprovalError <> 52912 THROW;
    SET @Denied = 1;
END CATCH;
IF @Denied = 0
BEGIN
    REVERT;
    THROW 53925, 'Synthetic workspace entered approval.', 1;
END;

UPDATE dbo.ApplicantSyntheticWorkspace
SET ClosedAtUtc = SYSUTCDATETIME()
WHERE ApplicationId = @ApplicationId;
DELETE FROM @V19;
INSERT @V19
EXEC dbo.GetApplicantSessionV19 @SessionTokenSha256=@SessionHash, @IdleExpiresAtUtc=@IdleAt;
IF EXISTS (SELECT 1 FROM @V19)
    THROW 53911, 'A closed synthetic workspace retained a session.', 1;
ROLLBACK TRANSACTION;

PRINT 'PASS 019 synthetic applicant workspace';
