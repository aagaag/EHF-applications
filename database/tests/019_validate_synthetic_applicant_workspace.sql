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
