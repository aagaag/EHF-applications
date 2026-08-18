SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE TABLE dbo.ApplicantSyntheticWorkspace
(
    ApplicationId uniqueidentifier NOT NULL,
    CreatedByIdentity nvarchar(255) NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantSyntheticWorkspace_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    ClosedAtUtc datetime2(7) NULL,
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicantSyntheticWorkspace PRIMARY KEY (ApplicationId),
    CONSTRAINT FK_ApplicantSyntheticWorkspace_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT UQ_ApplicantSyntheticWorkspace_Application UNIQUE (ApplicationId),
    CONSTRAINT CK_ApplicantSyntheticWorkspace_Actor CHECK (LEN(CreatedByIdentity) > 0),
    CONSTRAINT CK_ApplicantSyntheticWorkspace_Closure CHECK
        (ClosedAtUtc IS NULL OR ClosedAtUtc >= CreatedAtUtc)
);

ALTER TABLE dbo.ApplicantSession
DROP CONSTRAINT CK_ApplicantSession_AuthenticationSource;

ALTER TABLE dbo.ApplicantSession
ADD SyntheticActorIdentity nvarchar(255) NULL;

ALTER TABLE dbo.ApplicantSession
ADD CONSTRAINT CK_ApplicantSession_AuthenticationSource CHECK
    ((ApplicantInvitationId IS NOT NULL AND EntraObjectId IS NULL AND SyntheticActorIdentity IS NULL)
     OR (ApplicantInvitationId IS NULL AND EntraObjectId IS NOT NULL AND SyntheticActorIdentity IS NULL)
     OR (ApplicantInvitationId IS NULL AND EntraObjectId IS NULL AND SyntheticActorIdentity IS NOT NULL));

EXEC(N'
CREATE PROCEDURE dbo.CreateSyntheticApplicantWorkspace
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
    IF @ActorGroup <> N''EHF-Administrators'' OR LEN(@ActorIdentity) = 0
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
            (ApplicantId, LegalGivenNames, LegalFamilyName, SelfReportedGender)
        VALUES
            (@ApplicantId, N''Synthetic'', N''Applicant'', N''Prefer not to say'');
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

EXEC(N'
ALTER PROCEDURE dbo.GetApplicantSession
    @SessionTokenSha256 binary(32),
    @IdleExpiresAtUtc datetime2(7)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    UPDATE session_row
    SET LastSeenAtUtc = SYSUTCDATETIME(),
        IdleExpiresAtUtc = CASE
            WHEN @IdleExpiresAtUtc < AbsoluteExpiresAtUtc THEN @IdleExpiresAtUtc
            ELSE AbsoluteExpiresAtUtc END
    FROM dbo.ApplicantSession AS session_row
    WHERE SessionTokenSha256 = @SessionTokenSha256
      AND RevokedAtUtc IS NULL
      AND IdleExpiresAtUtc > SYSUTCDATETIME()
      AND AbsoluteExpiresAtUtc > SYSUTCDATETIME()
      AND NOT EXISTS
          (SELECT 1 FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
           WHERE workspace_row.ApplicationId = session_row.ApplicationId)
      AND (session_row.EntraObjectId IS NULL OR EXISTS
          (SELECT 1 FROM dbo.ApplicantEntraIdentity AS identity_row
           WHERE identity_row.EntraObjectId = session_row.EntraObjectId
             AND identity_row.ApplicationId = session_row.ApplicationId
             AND identity_row.Enabled = 1
             AND identity_row.DisabledAtUtc IS NULL));
    SELECT session_row.ApplicationId, session_row.CsrfTokenSha256,
           session_row.IdleExpiresAtUtc, session_row.AbsoluteExpiresAtUtc,
           session_row.ApplicantInvitationId, session_row.EntraObjectId
    FROM dbo.ApplicantSession AS session_row
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME()
      AND NOT EXISTS
          (SELECT 1 FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
           WHERE workspace_row.ApplicationId = session_row.ApplicationId)
      AND (session_row.EntraObjectId IS NULL OR EXISTS
          (SELECT 1 FROM dbo.ApplicantEntraIdentity AS identity_row
           WHERE identity_row.EntraObjectId = session_row.EntraObjectId
             AND identity_row.ApplicationId = session_row.ApplicationId
             AND identity_row.Enabled = 1
             AND identity_row.DisabledAtUtc IS NULL));
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantSessionV19
    @SessionTokenSha256 binary(32),
    @IdleExpiresAtUtc datetime2(7)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    UPDATE session_row
    SET LastSeenAtUtc = SYSUTCDATETIME(),
        IdleExpiresAtUtc = CASE
            WHEN @IdleExpiresAtUtc < AbsoluteExpiresAtUtc THEN @IdleExpiresAtUtc
            ELSE AbsoluteExpiresAtUtc END
    FROM dbo.ApplicantSession AS session_row
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME()
      AND ((session_row.SyntheticActorIdentity IS NULL
            AND (session_row.EntraObjectId IS NULL OR EXISTS
                (SELECT 1 FROM dbo.ApplicantEntraIdentity AS identity_row
                 WHERE identity_row.EntraObjectId = session_row.EntraObjectId
                   AND identity_row.ApplicationId = session_row.ApplicationId
                   AND identity_row.Enabled = 1
                   AND identity_row.DisabledAtUtc IS NULL)))
           OR (session_row.SyntheticActorIdentity IS NOT NULL AND EXISTS
                (SELECT 1 FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
                 WHERE workspace_row.ApplicationId = session_row.ApplicationId
                   AND workspace_row.CreatedByIdentity = session_row.SyntheticActorIdentity
                   AND workspace_row.ClosedAtUtc IS NULL)));
    SELECT session_row.ApplicationId, session_row.CsrfTokenSha256,
           session_row.IdleExpiresAtUtc, session_row.AbsoluteExpiresAtUtc,
           session_row.ApplicantInvitationId, session_row.EntraObjectId,
           session_row.SyntheticActorIdentity
    FROM dbo.ApplicantSession AS session_row
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME()
      AND ((session_row.SyntheticActorIdentity IS NULL
            AND (session_row.EntraObjectId IS NULL OR EXISTS
                (SELECT 1 FROM dbo.ApplicantEntraIdentity AS identity_row
                 WHERE identity_row.EntraObjectId = session_row.EntraObjectId
                   AND identity_row.ApplicationId = session_row.ApplicationId
                   AND identity_row.Enabled = 1
                   AND identity_row.DisabledAtUtc IS NULL)))
           OR (session_row.SyntheticActorIdentity IS NOT NULL AND EXISTS
                (SELECT 1 FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
                 WHERE workspace_row.ApplicationId = session_row.ApplicationId
                   AND workspace_row.CreatedByIdentity = session_row.SyntheticActorIdentity
                   AND workspace_row.ClosedAtUtc IS NULL)));
END;
');

EXEC(N'
ALTER PROCEDURE dbo.ListApplicantPreviews
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    IF @ActorGroup <> N''EHF-Administrators''
        THROW 52810, ''Administrator authorization is required.'', 1;
    SELECT application_row.ApplicationId,
           COALESCE(
               NULLIF(JSON_VALUE(identity_draft.DraftJson, ''$.fullName''), N''''),
               NULLIF(JSON_VALUE(baseline.ProjectionJson, ''$.applicant.fullName''), N''''),
               CONCAT(applicant.LegalGivenNames, N'' '', applicant.LegalFamilyName)
           ) AS ApplicantName,
           application_row.ApplicationStatus
    FROM dbo.ApplicantPortalBaseline AS baseline
    JOIN dbo.Application AS application_row
      ON application_row.ApplicationId = baseline.ApplicationId
    JOIN dbo.Applicant AS applicant
      ON applicant.ApplicantId = application_row.ApplicantId
    OUTER APPLY
    (
        SELECT TOP (1) draft_row.DraftJson
        FROM dbo.ApplicantSectionDraft AS draft_row
        WHERE draft_row.ApplicationId = application_row.ApplicationId
          AND draft_row.SectionCode = ''identity''
    ) AS identity_draft
    WHERE NOT EXISTS
    (
        SELECT 1 FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
        WHERE workspace_row.ApplicationId = application_row.ApplicationId
    )
    ORDER BY ApplicantName, application_row.ApplicationId;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.GetApplicantPreview
    @ApplicationId uniqueidentifier,
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128),
    @EmitResult bit = 1,
    @EmitDrafts bit = 1
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @ActorGroup <> N''EHF-Administrators'' OR LEN(LTRIM(RTRIM(@ActorIdentity))) = 0
        THROW 52810, ''Administrator authorization is required.'', 1;
    IF EXISTS
    (
        SELECT 1 FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
        WHERE workspace_row.ApplicationId = @ApplicationId
    )
        THROW 52910, ''Synthetic workspaces are unavailable to applicant preview.'', 1;

    DECLARE @ProjectionJson nvarchar(max),
            @ApplicantName nvarchar(401),
            @ApplicationStatus varchar(20);
    SELECT @ProjectionJson = baseline.ProjectionJson,
           @ApplicantName = COALESCE(
               NULLIF(JSON_VALUE(identity_draft.DraftJson, ''$.fullName''), N''''),
               NULLIF(JSON_VALUE(baseline.ProjectionJson, ''$.applicant.fullName''), N''''),
               CONCAT(applicant.LegalGivenNames, N'' '', applicant.LegalFamilyName)
           ),
           @ApplicationStatus = application_row.ApplicationStatus
    FROM dbo.ApplicantPortalBaseline AS baseline
    JOIN dbo.Application AS application_row
      ON application_row.ApplicationId = baseline.ApplicationId
    JOIN dbo.Applicant AS applicant
      ON applicant.ApplicantId = application_row.ApplicantId
    OUTER APPLY
    (
        SELECT TOP (1) draft_row.DraftJson
        FROM dbo.ApplicantSectionDraft AS draft_row
        WHERE draft_row.ApplicationId = application_row.ApplicationId
          AND draft_row.SectionCode = ''identity''
    ) AS identity_draft
    WHERE baseline.ApplicationId = @ApplicationId;
    IF @ProjectionJson IS NULL
        THROW 52811, ''The applicant preview is unavailable.'', 1;

    INSERT dbo.AuditEvent
        (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
    VALUES
        (@ApplicationId, ''APPLICANT_PREVIEW_OPENED'', LTRIM(RTRIM(@ActorIdentity)),
         ''Application'', @ApplicationId,
         (SELECT @ActorGroup AS actorGroup FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));
    IF @EmitResult = 1
    BEGIN
        SELECT @ApplicationId AS ApplicationId, @ApplicantName AS ApplicantName,
               @ApplicationStatus AS ApplicationStatus, @ProjectionJson AS ProjectionJson;
        IF @EmitDrafts = 1
        BEGIN
            SELECT draft_row.SectionCode, draft_row.DraftJson
            FROM dbo.ApplicantSectionDraft AS draft_row
            WHERE draft_row.ApplicationId = @ApplicationId
            ORDER BY draft_row.SectionCode;
        END;
    END;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.ProvisionApplicantAccessRequest
    @ApplicantAccessRequestId uniqueidentifier,
    @ApplicationId uniqueidentifier,
    @EntraObjectId uniqueidentifier,
    @ProvisionedByIdentity nvarchar(255),
    @ProvisionerGroup varchar(40)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @ProvisionerGroup NOT IN (''EHF-Administrators'', ''EHF-Trustees'')
       OR NULLIF(LTRIM(RTRIM(@ProvisionedByIdentity)), N'''') IS NULL
        THROW 52614, ''Administrator or trustee authorization is required.'', 1;
    BEGIN TRANSACTION;
    BEGIN TRY
        IF NOT EXISTS
        (
            SELECT 1 FROM dbo.ApplicantAccessRequest WITH (UPDLOCK, HOLDLOCK)
            WHERE ApplicantAccessRequestId = @ApplicantAccessRequestId
              AND RequestStatus = ''APPROVED''
        )
            THROW 52615, ''The approved access request is unavailable.'', 1;
        IF NOT EXISTS
        (
            SELECT 1 FROM dbo.Application WITH (UPDLOCK, HOLDLOCK)
            WHERE ApplicationId = @ApplicationId
        )
            THROW 52616, ''The application is unavailable.'', 1;
        IF EXISTS
        (
            SELECT 1 FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
            WHERE workspace_row.ApplicationId = @ApplicationId
        )
            THROW 52911, ''Synthetic workspaces cannot receive applicant identities.'', 1;
        IF EXISTS
        (
            SELECT 1 FROM dbo.ApplicantEntraIdentity WITH (UPDLOCK, HOLDLOCK)
            WHERE ApplicationId = @ApplicationId OR EntraObjectId = @EntraObjectId
        )
            THROW 52617, ''The applicant identity mapping already exists.'', 1;
        UPDATE dbo.ApplicantAccessRequest
        SET RequestStatus = ''PROVISIONED'',
            ProvisionedEntraObjectId = @EntraObjectId,
            ProvisionedAtUtc = SYSUTCDATETIME()
        WHERE ApplicantAccessRequestId = @ApplicantAccessRequestId;
        INSERT dbo.ApplicantEntraIdentity
            (ApplicationId, EntraObjectId, ApplicantAccessRequestId,
             IdentityKind, Enabled, LinkedByIdentity)
        VALUES
            (@ApplicationId, @EntraObjectId, @ApplicantAccessRequestId,
             ''APPLICANT'', 1, @ProvisionedByIdentity);
        COMMIT TRANSACTION;
        SELECT ApplicantAccessRequestId, RequestedEmail, RequestedDisplayName,
               RequestedAtUtc, RequestStatus, ReviewedByIdentity,
               ReviewerGroup, ReviewedAtUtc, ProvisionedEntraObjectId, ProvisionedAtUtc
        FROM dbo.ApplicantAccessRequest
        WHERE ApplicantAccessRequestId = @ApplicantAccessRequestId;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.ApproveApplicantSubmission
    @ApplicantFinalConfirmationId uniqueidentifier,
    @ReviewedByIdentity nvarchar(255),
    @ReviewerGroup varchar(40)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @ReviewerGroup NOT IN (''EHF-Administrators'', ''EHF-Trustees'')
       OR NULLIF(LTRIM(RTRIM(@ReviewedByIdentity)), N'''') IS NULL
        THROW 52641, ''Administrator or trustee authorization is required.'', 1;
    BEGIN TRANSACTION;
    BEGIN TRY
        DECLARE @ApplicationId uniqueidentifier;
        SELECT @ApplicationId = confirmation_row.ApplicationId
        FROM dbo.ApplicantFinalConfirmation AS confirmation_row WITH (UPDLOCK, HOLDLOCK)
        WHERE confirmation_row.ApplicantFinalConfirmationId = @ApplicantFinalConfirmationId
          AND confirmation_row.SupersededAtUtc IS NULL;
        IF @ApplicationId IS NULL
            THROW 52642, ''The applicant submission is unavailable.'', 1;
        IF EXISTS
        (
            SELECT 1 FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
            WHERE workspace_row.ApplicationId = @ApplicationId
        )
            THROW 52912, ''Synthetic workspaces cannot enter approval.'', 1;
        IF NOT EXISTS
        (
            SELECT 1 FROM dbo.ApplicantFinalReviewDecision
            WHERE ApplicantFinalConfirmationId = @ApplicantFinalConfirmationId
        )
        BEGIN
            INSERT dbo.ApplicantFinalReviewDecision
                (ApplicantFinalConfirmationId, ReviewDecision,
                 ReviewedByIdentity, ReviewerGroup)
            VALUES
                (@ApplicantFinalConfirmationId, ''APPROVED'',
                 @ReviewedByIdentity, @ReviewerGroup);
            UPDATE dbo.Application
            SET ApplicationStatus = ''CONFIRMED'',
                ConfirmedAtUtc = SYSUTCDATETIME(),
                UpdatedAtUtc = SYSUTCDATETIME()
            WHERE ApplicationId = @ApplicationId;
            EXEC dbo.PromoteApprovedApplicantDrafts
                 @ApplicationId = @ApplicationId,
                 @ApprovedByIdentity = @ReviewedByIdentity;
            INSERT dbo.AuditEvent
                (ApplicationId, EventType, ActorIdentity,
                 EntityType, EntityId, PayloadJson)
            VALUES
                (@ApplicationId, ''APPLICANT_CHANGES_APPROVED'', @ReviewedByIdentity,
                 ''ApplicantFinalConfirmation'', @ApplicantFinalConfirmationId,
                 (SELECT @ApplicationId AS applicationId FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));
        END;
        SELECT decision_row.ApplicantFinalConfirmationId,
               confirmation_row.ApplicationId, decision_row.ReviewDecision,
               decision_row.ReviewedByIdentity, decision_row.ReviewedAtUtc
        FROM dbo.ApplicantFinalReviewDecision AS decision_row
        JOIN dbo.ApplicantFinalConfirmation AS confirmation_row
          ON confirmation_row.ApplicantFinalConfirmationId =
             decision_row.ApplicantFinalConfirmationId
        WHERE decision_row.ApplicantFinalConfirmationId = @ApplicantFinalConfirmationId;
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.GetInternalApplicationMetrics
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    IF @ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')
        THROW 51725, ''The internal metrics role is not authorized.'', 1;
    SELECT
        COALESCE(JSON_VALUE(identity_section.SnapshotJson, ''$.fullName''),
                 CONCAT(applicant.LegalGivenNames, N'' '', applicant.LegalFamilyName))
            AS ApplicantName,
        COALESCE(JSON_VALUE(qualification_section.SnapshotJson, ''$.degreeCategory''),
                 JSON_VALUE(legacy_section.SnapshotJson, ''$.degree'')) AS Degree,
        TRY_CONVERT(decimal(8,2), JSON_VALUE(legacy_section.SnapshotJson, ''$.age_observation''))
            AS AgeObservation,
        TRY_CONVERT(decimal(8,2), JSON_VALUE(legacy_section.SnapshotJson, ''$.academic_age_observation''))
            AS AcademicAgeObservation,
        COALESCE(JSON_VALUE(identity_section.SnapshotJson, ''$.gender''),
                 applicant.SelfReportedGender) AS SelfReportedGender,
        COALESCE(TRY_CONVERT(int, JSON_VALUE(publication_section.SnapshotJson, ''$.firstAuthorPaperCount'')),
                 bibliometrics.FirstAuthorPaperCount) AS FirstAuthorPaperCount,
        COALESCE(TRY_CONVERT(int, JSON_VALUE(publication_section.SnapshotJson, ''$.lastAuthorPaperCount'')),
                 bibliometrics.LastAuthorPaperCount) AS LastAuthorPaperCount,
        COALESCE(TRY_CONVERT(int, JSON_VALUE(publication_section.SnapshotJson, ''$.totalPaperCount'')),
                 bibliometrics.TotalPaperCount) AS TotalPaperCount,
        COALESCE(TRY_CONVERT(int, JSON_VALUE(publication_section.SnapshotJson, ''$.hIndex'')),
                 TRY_CONVERT(int, JSON_VALUE(legacy_section.SnapshotJson, ''$.h_index''))) AS HIndex,
        COALESCE(TRY_CONVERT(bigint, JSON_VALUE(publication_section.SnapshotJson, ''$.applicantReportedCitationTotal'')),
                 TRY_CONVERT(bigint, JSON_VALUE(legacy_section.SnapshotJson, ''$.total_citations''))) AS TotalCitations,
        COALESCE(JSON_VALUE(publication_section.SnapshotJson, ''$.orcid''),
                 JSON_VALUE(legacy_section.SnapshotJson, ''$.orcid'')) AS Orcid,
        bibliometrics.GoogleScholarCitationCount AS GoogleScholarCitationCount,
        JSON_VALUE(legacy_section.SnapshotJson, ''$.identity_certainty'') AS IdentityCertainty
    FROM dbo.Application AS application_row
    JOIN dbo.FellowshipCall AS call_row
      ON call_row.FellowshipCallId = application_row.FellowshipCallId
    JOIN dbo.Applicant AS applicant
      ON applicant.ApplicantId = application_row.ApplicantId
    LEFT JOIN dbo.Bibliometrics AS bibliometrics
      ON bibliometrics.ApplicationId = application_row.ApplicationId
    OUTER APPLY
    (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion
     WHERE ApplicationId = application_row.ApplicationId AND SectionCode = ''identity''
     ORDER BY VersionNumber DESC) AS identity_section
    OUTER APPLY
    (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion
     WHERE ApplicationId = application_row.ApplicationId AND SectionCode = ''qualifications''
     ORDER BY VersionNumber DESC) AS qualification_section
    OUTER APPLY
    (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion
     WHERE ApplicationId = application_row.ApplicationId AND SectionCode = ''publications''
     ORDER BY VersionNumber DESC) AS publication_section
    OUTER APPLY
    (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion
     WHERE ApplicationId = application_row.ApplicationId
       AND SectionCode = ''LEGACY_REGISTER_OBSERVATIONS''
     ORDER BY VersionNumber DESC) AS legacy_section
    WHERE call_row.CallCode = N''EHF-2026''
      AND NOT EXISTS
      (
          SELECT 1 FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
          WHERE workspace_row.ApplicationId = application_row.ApplicationId
      )
    ORDER BY applicant.LegalFamilyName, applicant.LegalGivenNames;
END;
');

DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantSyntheticWorkspace TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.CreateSyntheticApplicantWorkspace TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetApplicantSessionV19 TO EHFApplicationRuntime;
