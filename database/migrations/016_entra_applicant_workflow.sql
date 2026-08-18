SET NOCOUNT ON;
SET XACT_ABORT ON;

ALTER TABLE dbo.EmploymentAffiliation
DROP CONSTRAINT CK_EmploymentAffiliation_ClinicalPercent;

ALTER TABLE dbo.EmploymentAffiliation
ADD CONSTRAINT CK_EmploymentAffiliation_ClinicalPercent CHECK
    (ClinicalWorkPercent IS NULL OR ClinicalWorkPercent BETWEEN 0.00 AND 100.00);

CREATE TABLE dbo.ApplicantAccessRequest
(
    ApplicantAccessRequestId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantAccessRequest_Id DEFAULT NEWSEQUENTIALID(),
    RequestedEmail nvarchar(320) NOT NULL,
    RequestedDisplayName nvarchar(300) NOT NULL,
    RequestStatus varchar(20) NOT NULL
        CONSTRAINT DF_ApplicantAccessRequest_Status DEFAULT 'PENDING',
    RequestedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantAccessRequest_RequestedAtUtc DEFAULT SYSUTCDATETIME(),
    ReviewedByIdentity nvarchar(255) NULL,
    ReviewerGroup varchar(40) NULL,
    ReviewedAtUtc datetime2(7) NULL,
    ProvisionedEntraObjectId uniqueidentifier NULL,
    ProvisionedAtUtc datetime2(7) NULL,
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicantAccessRequest PRIMARY KEY (ApplicantAccessRequestId),
    CONSTRAINT CK_ApplicantAccessRequest_Email CHECK
        (RequestedEmail LIKE N'%_@_%._%' AND LEN(RequestedEmail) <= 320),
    CONSTRAINT CK_ApplicantAccessRequest_Name CHECK (LEN(RequestedDisplayName) > 0),
    CONSTRAINT CK_ApplicantAccessRequest_Status CHECK
        (RequestStatus IN ('PENDING', 'APPROVED', 'REJECTED', 'PROVISIONED')),
    CONSTRAINT CK_ApplicantAccessRequest_Review CHECK
        ((RequestStatus = 'PENDING' AND ReviewedByIdentity IS NULL
          AND ReviewerGroup IS NULL AND ReviewedAtUtc IS NULL)
         OR (RequestStatus <> 'PENDING' AND LEN(ReviewedByIdentity) > 0
             AND ReviewerGroup IN ('EHF-Administrators', 'EHF-Trustees')
             AND ReviewedAtUtc IS NOT NULL)),
    CONSTRAINT CK_ApplicantAccessRequest_Provisioning CHECK
        ((RequestStatus <> 'PROVISIONED' AND ProvisionedEntraObjectId IS NULL
          AND ProvisionedAtUtc IS NULL)
         OR (RequestStatus = 'PROVISIONED' AND ProvisionedEntraObjectId IS NOT NULL
             AND ProvisionedAtUtc IS NOT NULL))
);

CREATE UNIQUE INDEX UX_ApplicantAccessRequest_OpenEmail
ON dbo.ApplicantAccessRequest (RequestedEmail)
WHERE RequestStatus IN ('PENDING', 'APPROVED');

CREATE UNIQUE INDEX UX_ApplicantAccessRequest_ProvisionedObject
ON dbo.ApplicantAccessRequest (ProvisionedEntraObjectId)
WHERE ProvisionedEntraObjectId IS NOT NULL;

CREATE TABLE dbo.ApplicantEntraIdentity
(
    ApplicantEntraIdentityId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantEntraIdentity_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    EntraObjectId uniqueidentifier NOT NULL,
    ApplicantAccessRequestId uniqueidentifier NULL,
    IdentityKind varchar(20) NOT NULL,
    Enabled bit NOT NULL CONSTRAINT DF_ApplicantEntraIdentity_Enabled DEFAULT 0,
    LinkedByIdentity nvarchar(255) NOT NULL,
    LinkedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantEntraIdentity_LinkedAtUtc DEFAULT SYSUTCDATETIME(),
    DisabledAtUtc datetime2(7) NULL,
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicantEntraIdentity PRIMARY KEY (ApplicantEntraIdentityId),
    CONSTRAINT FK_ApplicantEntraIdentity_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT FK_ApplicantEntraIdentity_Request FOREIGN KEY (ApplicantAccessRequestId)
        REFERENCES dbo.ApplicantAccessRequest (ApplicantAccessRequestId),
    CONSTRAINT UQ_ApplicantEntraIdentity_Application UNIQUE (ApplicationId),
    CONSTRAINT UQ_ApplicantEntraIdentity_Object UNIQUE (EntraObjectId),
    CONSTRAINT UQ_ApplicantEntraIdentity_ObjectApplication UNIQUE
        (EntraObjectId, ApplicationId),
    CONSTRAINT CK_ApplicantEntraIdentity_Kind CHECK
        (IdentityKind IN ('SYNTHETIC_TEST', 'LEGACY_APPLICANT', 'APPLICANT')),
    CONSTRAINT CK_ApplicantEntraIdentity_RequestSource CHECK
        ((IdentityKind = 'APPLICANT' AND ApplicantAccessRequestId IS NOT NULL)
         OR (IdentityKind IN ('SYNTHETIC_TEST', 'LEGACY_APPLICANT')
             AND ApplicantAccessRequestId IS NULL)),
    CONSTRAINT CK_ApplicantEntraIdentity_Actor CHECK (LEN(LinkedByIdentity) > 0),
    CONSTRAINT CK_ApplicantEntraIdentity_Enablement CHECK
        ((Enabled = 1 AND DisabledAtUtc IS NULL)
         OR (Enabled = 0))
);

EXEC(N'
CREATE TRIGGER dbo.TR_ApplicantEntraIdentity_ValidateRequest
ON dbo.ApplicantEntraIdentity
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS
    (
        SELECT 1 FROM inserted AS identity_row
        LEFT JOIN dbo.ApplicantAccessRequest AS request_row
          ON request_row.ApplicantAccessRequestId = identity_row.ApplicantAccessRequestId
         AND request_row.RequestStatus = ''PROVISIONED''
         AND request_row.ProvisionedEntraObjectId = identity_row.EntraObjectId
        WHERE identity_row.IdentityKind = ''APPLICANT''
          AND request_row.ApplicantAccessRequestId IS NULL
    )
        THROW 52613, ''Applicant identity provisioning requires its approved access request.'', 1;
END;
');

CREATE TABLE dbo.ApplicantPortalBaseline
(
    ApplicationId uniqueidentifier NOT NULL,
    ProjectionJson nvarchar(max) NOT NULL,
    PatternSourceSha256 binary(32) NULL,
    CreatedByIdentity nvarchar(255) NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantPortalBaseline_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicantPortalBaseline PRIMARY KEY (ApplicationId),
    CONSTRAINT FK_ApplicantPortalBaseline_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT CK_ApplicantPortalBaseline_Json CHECK (ISJSON(ProjectionJson) = 1),
    CONSTRAINT CK_ApplicantPortalBaseline_Actor CHECK (LEN(CreatedByIdentity) > 0)
);

INSERT dbo.ApplicantPortalBaseline
    (ApplicationId, ProjectionJson, CreatedByIdentity)
SELECT application_row.ApplicationId,
       (SELECT
          JSON_QUERY((SELECT
            CONCAT(applicant_row.LegalGivenNames, N' ', applicant_row.LegalFamilyName) AS fullName,
            applicant_row.PreferredName AS preferredName,
            registered_email.ContactValue AS registeredEmail,
            alternative_email.ContactValue AS alternativeEmail,
            telephone.ContactValue AS telephone,
            applicant_row.BirthMonth AS birthMonth,
            applicant_row.BirthYear AS birthYear,
            applicant_row.SelfReportedGender AS gender,
            CAST(NULL AS nvarchar(200)) AS genderSelfDescription,
            employment.InstitutionName AS institute,
            CAST(NULL AS nvarchar(300)) AS principalInvestigator,
            employment.PositionTitle AS positionTitle,
            CAST(NULL AS nvarchar(200)) AS postdoctoralEmploymentStatus,
            CAST(NULL AS date) AS employmentStartDate,
            CAST(NULL AS date) AS employmentEndDate,
            CAST(NULL AS date) AS futureStartDate,
            CAST(NULL AS nvarchar(500)) AS researchArea,
            employment.ClinicalWorkPercent AS clinicalWorkPercent,
            CASE WHEN bibliometrics.FirstAuthorPaperCount IS NULL THEN NULL
                 WHEN bibliometrics.FirstAuthorPaperCount > 0 THEN CAST(1 AS bit)
                 ELSE CAST(0 AS bit) END AS firstAuthorDeclaration,
            CASE
              WHEN qualification.DegreeType IS NOT NULL THEN qualification.DegreeType
              WHEN UPPER(JSON_VALUE(register_snapshot.SnapshotJson, '$.degree')) LIKE '%MD%PHD%'
                THEN 'MD_PHD'
              WHEN UPPER(JSON_VALUE(register_snapshot.SnapshotJson, '$.degree')) LIKE '%PHD%'
                THEN 'PHD'
              WHEN UPPER(JSON_VALUE(register_snapshot.SnapshotJson, '$.degree')) LIKE '%MD%'
                THEN 'MD'
              ELSE NULL END AS degreeCategory,
            qualification.PhdDate AS phdDate,
            bibliometrics.FirstAuthorPaperCount AS firstAuthorPaperCount,
            bibliometrics.LastAuthorPaperCount AS lastAuthorPaperCount,
            bibliometrics.TotalPaperCount AS totalPaperCount,
            TRY_CONVERT(int, JSON_VALUE(register_snapshot.SnapshotJson, '$.h_index')) AS hIndex,
            TRY_CONVERT(bigint, JSON_VALUE(register_snapshot.SnapshotJson, '$.total_citations'))
                AS applicantReportedCitationTotal,
            JSON_VALUE(register_snapshot.SnapshotJson, '$.orcid') AS orcid,
            CAST(NULL AS nvarchar(1000)) AS googleScholarProfileUrl,
            CAST(NULL AS bit) AS noGoogleScholarProfile,
            bibliometrics.GoogleScholarCitationCount AS googleScholarCitationTotal,
            contribution.StatementText AS contributionStatement,
            CAST(0 AS bit) AS locked
           FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES)) AS applicant,
          JSON_QUERY(N'{}') AS sections,
          JSON_QUERY(N'[]') AS documents
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
       N'MIGRATION_016'
FROM dbo.Application AS application_row
JOIN dbo.Applicant AS applicant_row
  ON applicant_row.ApplicantId = application_row.ApplicantId
LEFT JOIN dbo.Bibliometrics AS bibliometrics
  ON bibliometrics.ApplicationId = application_row.ApplicationId
LEFT JOIN dbo.ContributionStatement AS contribution
  ON contribution.ApplicationId = application_row.ApplicationId
OUTER APPLY
(
    SELECT TOP (1) ContactValue FROM dbo.ApplicantContact
    WHERE ApplicantId = applicant_row.ApplicantId
      AND ContactType = 'REGISTERED_EMAIL' AND IsPrimary = 1
) AS registered_email
OUTER APPLY
(
    SELECT TOP (1) ContactValue FROM dbo.ApplicantContact
    WHERE ApplicantId = applicant_row.ApplicantId
      AND ContactType = 'ALTERNATIVE_EMAIL'
    ORDER BY IsPrimary DESC, ApplicantContactId
) AS alternative_email
OUTER APPLY
(
    SELECT TOP (1) ContactValue FROM dbo.ApplicantContact
    WHERE ApplicantId = applicant_row.ApplicantId AND ContactType = 'TELEPHONE'
    ORDER BY IsPrimary DESC, ApplicantContactId
) AS telephone
OUTER APPLY
(
    SELECT TOP (1) InstitutionName, PositionTitle, ClinicalWorkPercent
    FROM dbo.EmploymentAffiliation
    WHERE ApplicationId = application_row.ApplicationId
    ORDER BY EmploymentAffiliationId
) AS employment
OUTER APPLY
(
    SELECT TOP (1) DegreeType, PhdDate FROM dbo.Qualification
    WHERE ApplicationId = application_row.ApplicationId
    ORDER BY QualificationId
) AS qualification
OUTER APPLY
(
    SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion
    WHERE ApplicationId = application_row.ApplicationId
      AND SectionCode = 'LEGACY_REGISTER_OBSERVATIONS'
    ORDER BY VersionNumber DESC
) AS register_snapshot;

ALTER TABLE dbo.ApplicantSession
ALTER COLUMN ApplicantInvitationId uniqueidentifier NULL;

ALTER TABLE dbo.ApplicantSession
ADD EntraObjectId uniqueidentifier NULL;

ALTER TABLE dbo.ApplicantSession
ADD CONSTRAINT FK_ApplicantSession_EntraIdentity FOREIGN KEY (EntraObjectId, ApplicationId)
        REFERENCES dbo.ApplicantEntraIdentity (EntraObjectId, ApplicationId),
    CONSTRAINT CK_ApplicantSession_AuthenticationSource CHECK
        ((ApplicantInvitationId IS NOT NULL AND EntraObjectId IS NULL)
         OR (ApplicantInvitationId IS NULL AND EntraObjectId IS NOT NULL));

CREATE TABLE dbo.ApplicantFinalReviewDecision
(
    ApplicantFinalReviewDecisionId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantFinalReviewDecision_Id DEFAULT NEWSEQUENTIALID(),
    ApplicantFinalConfirmationId uniqueidentifier NOT NULL,
    ReviewDecision varchar(12) NOT NULL,
    ReviewedByIdentity nvarchar(255) NOT NULL,
    ReviewerGroup varchar(40) NOT NULL,
    ReviewedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantFinalReviewDecision_ReviewedAtUtc DEFAULT SYSUTCDATETIME(),
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantFinalReviewDecision_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ApplicantFinalReviewDecision PRIMARY KEY (ApplicantFinalReviewDecisionId),
    CONSTRAINT FK_ApplicantFinalReviewDecision_Confirmation FOREIGN KEY
        (ApplicantFinalConfirmationId)
        REFERENCES dbo.ApplicantFinalConfirmation (ApplicantFinalConfirmationId),
    CONSTRAINT UQ_ApplicantFinalReviewDecision_Confirmation UNIQUE
        (ApplicantFinalConfirmationId),
    CONSTRAINT CK_ApplicantFinalReviewDecision_Value CHECK
        (ReviewDecision IN ('APPROVED', 'REJECTED')),
    CONSTRAINT CK_ApplicantFinalReviewDecision_Actor CHECK
        (LEN(ReviewedByIdentity) > 0
         AND ReviewerGroup IN ('EHF-Administrators', 'EHF-Trustees'))
);

CREATE TABLE dbo.ApplicantDocumentReviewDecision
(
    ApplicantDocumentReviewDecisionId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantDocumentReviewDecision_Id DEFAULT NEWSEQUENTIALID(),
    ApplicantDocumentSubmissionId uniqueidentifier NOT NULL,
    ReviewDecision varchar(12) NOT NULL,
    ReviewedByIdentity nvarchar(255) NOT NULL,
    ReviewerGroup varchar(40) NOT NULL,
    ReviewReason nvarchar(1000) NULL,
    ReviewedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantDocumentReviewDecision_ReviewedAtUtc DEFAULT SYSUTCDATETIME(),
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantDocumentReviewDecision_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ApplicantDocumentReviewDecision PRIMARY KEY
        (ApplicantDocumentReviewDecisionId),
    CONSTRAINT FK_ApplicantDocumentReviewDecision_Submission FOREIGN KEY
        (ApplicantDocumentSubmissionId)
        REFERENCES dbo.ApplicantDocumentSubmission (ApplicantDocumentSubmissionId),
    CONSTRAINT UQ_ApplicantDocumentReviewDecision_Submission UNIQUE
        (ApplicantDocumentSubmissionId),
    CONSTRAINT CK_ApplicantDocumentReviewDecision_Value CHECK
        (ReviewDecision IN ('ACCEPTED', 'REJECTED')),
    CONSTRAINT CK_ApplicantDocumentReviewDecision_Actor CHECK
        (LEN(ReviewedByIdentity) > 0
         AND ReviewerGroup IN ('EHF-Administrators', 'EHF-Trustees')),
    CONSTRAINT CK_ApplicantDocumentReviewDecision_Reason CHECK
        (ReviewDecision = 'ACCEPTED' OR LEN(ReviewReason) > 0)
);

EXEC(N'
CREATE TRIGGER dbo.TR_ApplicantFinalReviewDecision_AppendOnly
ON dbo.ApplicantFinalReviewDecision
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 52640, ''Applicant final review decisions are append-only.'', 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_ApplicantDocumentReviewDecision_AppendOnly
ON dbo.ApplicantDocumentReviewDecision
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 52643, ''Applicant document review decisions are append-only.'', 1;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicationForEntraApplicant
    @EntraObjectId uniqueidentifier
AS
BEGIN
    SET NOCOUNT ON;
    SELECT identity_row.ApplicationId
    FROM dbo.ApplicantEntraIdentity AS identity_row
    WHERE identity_row.EntraObjectId = @EntraObjectId
      AND identity_row.Enabled = 1
      AND identity_row.DisabledAtUtc IS NULL;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.RequestApplicantAccess
    @RequestedEmail nvarchar(320), @RequestedDisplayName nvarchar(300)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRANSACTION;
    BEGIN TRY
        DECLARE @RequestId uniqueidentifier;
        SELECT @RequestId = ApplicantAccessRequestId
        FROM dbo.ApplicantAccessRequest WITH (UPDLOCK, HOLDLOCK)
        WHERE RequestedEmail = LOWER(LTRIM(RTRIM(@RequestedEmail)))
          AND RequestStatus IN (''PENDING'', ''APPROVED'');
        IF @RequestId IS NULL
        BEGIN
            SET @RequestId = NEWID();
            INSERT dbo.ApplicantAccessRequest
                (ApplicantAccessRequestId, RequestedEmail, RequestedDisplayName)
            VALUES
                (@RequestId, LOWER(LTRIM(RTRIM(@RequestedEmail))),
                 LTRIM(RTRIM(@RequestedDisplayName)));
        END;
        SELECT ApplicantAccessRequestId, RequestedEmail, RequestedDisplayName,
               RequestedAtUtc, RequestStatus, ReviewedByIdentity,
               ReviewerGroup, ReviewedAtUtc
        FROM dbo.ApplicantAccessRequest
        WHERE ApplicantAccessRequestId = @RequestId;
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ListPendingApplicantAccessRequests
AS
BEGIN
    SET NOCOUNT ON;
    SELECT ApplicantAccessRequestId, RequestedEmail, RequestedDisplayName,
           RequestedAtUtc, RequestStatus, ReviewedByIdentity,
           ReviewerGroup, ReviewedAtUtc
    FROM dbo.ApplicantAccessRequest
    WHERE RequestStatus IN (''PENDING'', ''APPROVED'')
    ORDER BY RequestedAtUtc, ApplicantAccessRequestId;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ReviewApplicantAccessRequest
    @ApplicantAccessRequestId uniqueidentifier, @Decision varchar(20),
    @ReviewedByIdentity nvarchar(255), @ReviewerGroup varchar(40)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @Decision NOT IN (''APPROVED'', ''REJECTED'')
       OR @ReviewerGroup NOT IN (''EHF-Administrators'', ''EHF-Trustees'')
       OR NULLIF(LTRIM(RTRIM(@ReviewedByIdentity)), N'''') IS NULL
        THROW 52611, ''A valid access-request review is required.'', 1;
    UPDATE dbo.ApplicantAccessRequest
    SET RequestStatus = @Decision, ReviewedByIdentity = @ReviewedByIdentity,
        ReviewerGroup = @ReviewerGroup, ReviewedAtUtc = SYSUTCDATETIME()
    WHERE ApplicantAccessRequestId = @ApplicantAccessRequestId
      AND RequestStatus = ''PENDING'';
    IF @@ROWCOUNT = 0
        THROW 52612, ''The access request is unavailable.'', 1;
    SELECT ApplicantAccessRequestId, RequestedEmail, RequestedDisplayName,
           RequestedAtUtc, RequestStatus, ReviewedByIdentity,
           ReviewerGroup, ReviewedAtUtc
    FROM dbo.ApplicantAccessRequest
    WHERE ApplicantAccessRequestId = @ApplicantAccessRequestId;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ProvisionApplicantAccessRequest
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
CREATE PROCEDURE dbo.CreateEntraApplicantSession
    @EntraObjectId uniqueidentifier,
    @SessionTokenSha256 binary(32),
    @CsrfTokenSha256 binary(32),
    @IdleExpiresAtUtc datetime2(7),
    @AbsoluteExpiresAtUtc datetime2(7)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @ApplicationId uniqueidentifier;
    SELECT @ApplicationId = identity_row.ApplicationId
    FROM dbo.ApplicantEntraIdentity AS identity_row
    WHERE identity_row.EntraObjectId = @EntraObjectId
      AND identity_row.Enabled = 1
      AND identity_row.DisabledAtUtc IS NULL;
    IF @ApplicationId IS NULL
        THROW 52620, ''The applicant identity is unavailable.'', 1;
    INSERT dbo.ApplicantSession
        (ApplicantInvitationId, ApplicationId, EntraObjectId,
         SessionTokenSha256, CsrfTokenSha256, IdleExpiresAtUtc, AbsoluteExpiresAtUtc)
    VALUES
        (NULL, @ApplicationId, @EntraObjectId,
         @SessionTokenSha256, @CsrfTokenSha256, @IdleExpiresAtUtc, @AbsoluteExpiresAtUtc);
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantSession
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
      AND (session_row.EntraObjectId IS NULL OR EXISTS
          (SELECT 1 FROM dbo.ApplicantEntraIdentity AS identity_row
           WHERE identity_row.EntraObjectId = session_row.EntraObjectId
             AND identity_row.ApplicationId = session_row.ApplicationId
             AND identity_row.Enabled = 1
             AND identity_row.DisabledAtUtc IS NULL));
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantProjection
    @SessionTokenSha256 binary(32)
AS
BEGIN
    SET NOCOUNT ON;
    SELECT baseline.ApplicationId,
           JSON_MODIFY(
             baseline.ProjectionJson, ''$.documents'',
             JSON_QUERY(COALESCE((
               SELECT document_row.DocumentId AS documentId,
                      version_row.DocumentVersionId AS versionId,
                      slot_row.SlotCode AS slotCode,
                      COALESCE(submission_row.SubmittedDisplayName,
                               slot_row.SlotLabel) AS displayName,
                      CONVERT(varchar(64), object_row.PlaintextSha256, 2) AS sha256,
                      object_row.ByteSize AS byteSize,
                      object_row.MediaType AS mediaType,
                      ''AVAILABLE'' AS status,
                      CAST(CASE WHEN slot_row.ApplicantUploadMode IN
                           (''MISSING'', ''REPLACEMENT'') THEN 1 ELSE 0 END AS bit)
                           AS uploadOpen,
                      CAST(CASE WHEN slot_row.ApplicantUploadMode = ''REPLACEMENT''
                           THEN 1 ELSE 0 END AS bit) AS replacementOpen,
                      CONVERT(varchar(16), slot_row.RowVersion, 2) AS rowVersion,
                      ''APPLICANT_VISIBLE'' AS classification,
                      document_row.DocumentType AS documentType,
                      CAST(0 AS bit) AS recommendationLinked
               FROM dbo.DocumentSlot AS slot_row
               JOIN dbo.Document AS document_row
                 ON document_row.DocumentSlotId = slot_row.DocumentSlotId
               JOIN dbo.DocumentVersion AS version_row
                 ON version_row.DocumentVersionId = slot_row.ActiveDocumentVersionId
                AND version_row.DocumentId = document_row.DocumentId
               JOIN dbo.StoredObject AS object_row
                 ON object_row.StoredObjectId = version_row.StoredObjectId
               OUTER APPLY
               (
                   SELECT TOP (1) submission.SubmittedDisplayName
                   FROM dbo.ApplicantDocumentSubmission AS submission
                   WHERE submission.DocumentVersionId = version_row.DocumentVersionId
                   ORDER BY submission.SubmittedAtUtc DESC,
                            submission.ApplicantDocumentSubmissionId DESC
               ) AS submission_row
               WHERE slot_row.ApplicationId = baseline.ApplicationId
                 AND slot_row.ApplicantVisible = 1
                 AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
                 AND document_row.DocumentType <> ''RECOMMENDATION_LETTER''
                 AND NOT EXISTS
                    (SELECT 1 FROM dbo.Recommendation AS recommendation_row
                     WHERE recommendation_row.DocumentId = document_row.DocumentId)
                 AND (EXISTS
                    (SELECT 1 FROM dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
                     WHERE visible_version.DocumentVersionId = version_row.DocumentVersionId)
                   OR EXISTS
                    (SELECT 1 FROM dbo.ApplicantDocumentSubmission AS accepted_submission
                     JOIN dbo.ApplicantDocumentReviewDecision AS decision_row
                       ON decision_row.ApplicantDocumentSubmissionId =
                          accepted_submission.ApplicantDocumentSubmissionId
                      AND decision_row.ReviewDecision = ''ACCEPTED''
                     WHERE accepted_submission.DocumentVersionId =
                           version_row.DocumentVersionId))
               ORDER BY slot_row.SlotCode
               FOR JSON PATH, INCLUDE_NULL_VALUES
             ), N''[]''))) AS ProjectionJson
    FROM dbo.ApplicantSession AS session_row
    JOIN dbo.ApplicantPortalBaseline AS baseline
      ON baseline.ApplicationId = session_row.ApplicationId
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME();
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantSectionDraft
    @SessionTokenSha256 binary(32),
    @SectionCode varchar(80)
AS
BEGIN
    SET NOCOUNT ON;
    SELECT draft_row.ApplicationId, draft_row.SectionCode,
           draft_row.DraftJson, draft_row.RowVersion
    FROM dbo.ApplicantSession AS session_row
    JOIN dbo.ApplicantSectionDraft AS draft_row
      ON draft_row.ApplicationId = session_row.ApplicationId
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME()
      AND draft_row.SectionCode = @SectionCode;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantSectionConfirmation
    @SessionTokenSha256 binary(32),
    @SectionCode varchar(80)
AS
BEGIN
    SET NOCOUNT ON;
    SELECT confirmation_row.ApplicationId, confirmation_row.SectionCode,
           confirmation_row.CanonicalSectionSha256,
           confirmation_row.DraftRowVersion, confirmation_row.ConfirmedAtUtc
    FROM dbo.ApplicantSession AS session_row
    JOIN dbo.ApplicantSectionConfirmation AS confirmation_row
      ON confirmation_row.ApplicationId = session_row.ApplicationId
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME()
      AND confirmation_row.SectionCode = @SectionCode
    ORDER BY confirmation_row.ConfirmedAtUtc DESC;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.GetApplicantDocumentSlots
    @SessionTokenSha256 binary(32)
AS
BEGIN
    SET NOCOUNT ON;
    SELECT slot_row.DocumentSlotId, slot_row.SlotCode, slot_row.SlotLabel,
           slot_row.RequiredForCompletion, slot_row.ApplicantUploadMode,
           slot_row.RowVersion, slot_row.ActiveDocumentVersionId,
           document_row.DocumentId, document_row.DocumentType
    FROM dbo.ApplicantSession AS session_row
    JOIN dbo.DocumentSlot AS slot_row
      ON slot_row.ApplicationId = session_row.ApplicationId
    LEFT JOIN dbo.Document AS document_row
      ON document_row.DocumentSlotId = slot_row.DocumentSlotId
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME()
      AND slot_row.ApplicantVisible = 1
      AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
      AND (document_row.DocumentId IS NULL
           OR (document_row.DocumentType <> ''RECOMMENDATION_LETTER''
               AND NOT EXISTS
                   (SELECT 1 FROM dbo.Recommendation AS recommendation_row
                    WHERE recommendation_row.DocumentId = document_row.DocumentId)))
      AND (slot_row.ActiveDocumentVersionId IS NULL
           OR EXISTS
              (SELECT 1 FROM dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
               WHERE visible_version.DocumentVersionId = slot_row.ActiveDocumentVersionId)
           OR EXISTS
              (SELECT 1
               FROM dbo.ApplicantDocumentSubmission AS submission_row
               JOIN dbo.ApplicantDocumentReviewDecision AS decision_row
                 ON decision_row.ApplicantDocumentSubmissionId =
                    submission_row.ApplicantDocumentSubmissionId
                AND decision_row.ReviewDecision = ''ACCEPTED''
               WHERE submission_row.DocumentVersionId = slot_row.ActiveDocumentVersionId));
END;
');

EXEC(N'
CREATE PROCEDURE dbo.RegisterApplicantDocumentSubmission
    @SessionTokenSha256 binary(32), @DocumentSlotId uniqueidentifier,
    @ExpectedRowVersion binary(8), @DocumentId uniqueidentifier,
    @DocumentVersionId uniqueidentifier, @StoredObjectId uniqueidentifier,
    @ObjectKey varchar(32), @KeyVersion smallint, @EnvelopeVersion tinyint,
    @AesGcmNonce binary(12), @PlaintextSha256 binary(32),
    @CiphertextSha256 binary(32), @ByteSize bigint, @MediaType varchar(100),
    @PageCount int, @ScanEngine varchar(100), @ScanSignature nvarchar(200),
    @ScannedAtUtc datetime2(7), @SubmittedDisplayName nvarchar(255)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRANSACTION;
    BEGIN TRY
        DECLARE @ApplicationId uniqueidentifier, @ApplicantSessionId uniqueidentifier,
                @ExistingDocumentId uniqueidentifier, @DocumentType varchar(40),
                @VersionNumber int, @SlotAuthorized bit = 0;
        SELECT @ApplicationId = session_row.ApplicationId,
               @ApplicantSessionId = session_row.ApplicantSessionId
        FROM dbo.ApplicantSession AS session_row WITH (UPDLOCK, HOLDLOCK)
        WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
          AND session_row.RevokedAtUtc IS NULL
          AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
          AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME();
        SELECT @SlotAuthorized = 1,
               @ExistingDocumentId = document_row.DocumentId,
               @DocumentType = document_row.DocumentType
        FROM dbo.DocumentSlot AS slot_row WITH (UPDLOCK, HOLDLOCK)
        LEFT JOIN dbo.Document AS document_row
          ON document_row.DocumentSlotId = slot_row.DocumentSlotId
        WHERE slot_row.DocumentSlotId = @DocumentSlotId
          AND slot_row.ApplicationId = @ApplicationId
          AND slot_row.ApplicantVisible = 1
          AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
          AND slot_row.ApplicantUploadMode IN (''MISSING'', ''REPLACEMENT'')
          AND slot_row.RowVersion = @ExpectedRowVersion
          AND (document_row.DocumentId IS NULL
               OR (document_row.DocumentType <> ''RECOMMENDATION_LETTER''
                   AND NOT EXISTS
                       (SELECT 1 FROM dbo.Recommendation AS recommendation_row
                        WHERE recommendation_row.DocumentId = document_row.DocumentId)));
        IF @ApplicationId IS NULL OR @ApplicantSessionId IS NULL
           OR @SlotAuthorized <> 1
            THROW 52650, ''The applicant document slot is unavailable.'', 1;
        IF @ExistingDocumentId IS NULL
        BEGIN
            SET @DocumentType = CASE
                WHEN EXISTS (SELECT 1 FROM dbo.DocumentSlot WHERE DocumentSlotId = @DocumentSlotId AND SlotCode = ''CV'') THEN ''CV''
                WHEN EXISTS (SELECT 1 FROM dbo.DocumentSlot WHERE DocumentSlotId = @DocumentSlotId AND SlotCode = ''PUBLICATION_LIST'') THEN ''PUBLICATION_LIST''
                WHEN EXISTS (SELECT 1 FROM dbo.DocumentSlot WHERE DocumentSlotId = @DocumentSlotId AND SlotCode = ''RESEARCH_PLAN'') THEN ''RESEARCH_PLAN''
                WHEN EXISTS (SELECT 1 FROM dbo.DocumentSlot WHERE DocumentSlotId = @DocumentSlotId AND SlotCode LIKE ''COVER_LETTER%'') THEN ''COVER_LETTER''
                ELSE ''OTHER'' END;
            INSERT dbo.Document (DocumentId, DocumentSlotId, DocumentType, CreatedByIdentity)
            VALUES (@DocumentId, @DocumentSlotId, @DocumentType, N''APPLICANT'');
            SET @ExistingDocumentId = @DocumentId;
        END;
        ELSE IF @ExistingDocumentId <> @DocumentId
            THROW 52651, ''The applicant document changed before upload.'', 1;
        SELECT @VersionNumber = ISNULL(MAX(VersionNumber), 0) + 1
        FROM dbo.DocumentVersion WITH (UPDLOCK, HOLDLOCK)
        WHERE DocumentId = @ExistingDocumentId;
        INSERT dbo.StoredObject
            (StoredObjectId, ObjectKey, KeyVersion, EnvelopeVersion, AesGcmNonce,
             PlaintextSha256, CiphertextSha256, ByteSize, MediaType, PageCount,
             ScanEngine, ScanSignature, ScannedAtUtc, ScanResult, CreatedByIdentity)
        VALUES
            (@StoredObjectId, @ObjectKey, @KeyVersion, @EnvelopeVersion, @AesGcmNonce,
             @PlaintextSha256, @CiphertextSha256, @ByteSize, @MediaType, @PageCount,
             @ScanEngine, @ScanSignature, @ScannedAtUtc, ''CLEAN'', N''APPLICANT'');
        INSERT dbo.DocumentVersion
            (DocumentVersionId, DocumentId, StoredObjectId, VersionNumber,
             Classification, CreatedByIdentity)
        VALUES
            (@DocumentVersionId, @ExistingDocumentId, @StoredObjectId,
             @VersionNumber, ''UNREVIEWED'', N''APPLICANT'');
        INSERT dbo.ApplicantDocumentSubmission
            (ApplicationId, DocumentSlotId, DocumentVersionId, ApplicantSessionId,
             SubmissionStatus, SubmittedDisplayName)
        VALUES
            (@ApplicationId, @DocumentSlotId, @DocumentVersionId, @ApplicantSessionId,
             ''PENDING'', @SubmittedDisplayName);
        UPDATE dbo.DocumentSlot
        SET ApplicantUploadMode = ''CLOSED'', UploadReason = NULL,
            OpenedByIdentity = NULL, OpenedAtUtc = NULL
        WHERE DocumentSlotId = @DocumentSlotId;
        SELECT @ApplicationId, @ExistingDocumentId, @DocumentVersionId,
               @VersionNumber, ApplicantDocumentSubmissionId
        FROM dbo.ApplicantDocumentSubmission
        WHERE DocumentVersionId = @DocumentVersionId;
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantDocumentDownload
    @SessionTokenSha256 binary(32), @DocumentSlotId uniqueidentifier
AS
BEGIN
    SET NOCOUNT ON;
    SELECT slot_row.ApplicationId, document_row.DocumentId,
           version_row.DocumentVersionId, object_row.StoredObjectId,
           object_row.ObjectKey, object_row.KeyVersion, object_row.EnvelopeVersion,
           object_row.AesGcmNonce, object_row.PlaintextSha256,
           object_row.CiphertextSha256, object_row.ByteSize
    FROM dbo.ApplicantSession AS session_row
    JOIN dbo.DocumentSlot AS slot_row
      ON slot_row.ApplicationId = session_row.ApplicationId
     AND slot_row.DocumentSlotId = @DocumentSlotId
    JOIN dbo.Document AS document_row
      ON document_row.DocumentSlotId = slot_row.DocumentSlotId
    JOIN dbo.DocumentVersion AS version_row
      ON version_row.DocumentVersionId = slot_row.ActiveDocumentVersionId
     AND version_row.DocumentId = document_row.DocumentId
    JOIN dbo.StoredObject AS object_row
      ON object_row.StoredObjectId = version_row.StoredObjectId
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME()
      AND slot_row.ApplicantVisible = 1
      AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
      AND document_row.DocumentType <> ''RECOMMENDATION_LETTER''
      AND NOT EXISTS
          (SELECT 1 FROM dbo.Recommendation AS recommendation_row
           WHERE recommendation_row.DocumentId = document_row.DocumentId)
      AND (EXISTS
          (SELECT 1 FROM dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
           WHERE visible_version.DocumentVersionId = version_row.DocumentVersionId)
       OR EXISTS
          (SELECT 1
           FROM dbo.ApplicantDocumentSubmission AS submission_row
           JOIN dbo.ApplicantDocumentReviewDecision AS decision_row
             ON decision_row.ApplicantDocumentSubmissionId =
                submission_row.ApplicantDocumentSubmissionId
            AND decision_row.ReviewDecision = ''ACCEPTED''
           WHERE submission_row.DocumentVersionId = version_row.DocumentVersionId));
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantFinalDocuments
    @SessionTokenSha256 binary(32)
AS
BEGIN
    SET NOCOUNT ON;
    SELECT slot_row.SlotCode, version_row.DocumentVersionId,
           object_row.PlaintextSha256
    FROM dbo.ApplicantSession AS session_row
    JOIN dbo.DocumentSlot AS slot_row
      ON slot_row.ApplicationId = session_row.ApplicationId
    JOIN dbo.Document AS document_row
      ON document_row.DocumentSlotId = slot_row.DocumentSlotId
    JOIN dbo.DocumentVersion AS version_row
      ON version_row.DocumentVersionId = slot_row.ActiveDocumentVersionId
     AND version_row.DocumentId = document_row.DocumentId
    JOIN dbo.StoredObject AS object_row
      ON object_row.StoredObjectId = version_row.StoredObjectId
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME()
      AND slot_row.ApplicantVisible = 1
      AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
      AND document_row.DocumentType <> ''RECOMMENDATION_LETTER''
      AND NOT EXISTS
          (SELECT 1 FROM dbo.Recommendation AS recommendation_row
           WHERE recommendation_row.DocumentId = document_row.DocumentId)
      AND (EXISTS
          (SELECT 1 FROM dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
           WHERE visible_version.DocumentVersionId = version_row.DocumentVersionId)
       OR EXISTS
          (SELECT 1
           FROM dbo.ApplicantDocumentSubmission AS submission_row
           JOIN dbo.ApplicantDocumentReviewDecision AS decision_row
             ON decision_row.ApplicantDocumentSubmissionId =
                submission_row.ApplicantDocumentSubmissionId
            AND decision_row.ReviewDecision = ''ACCEPTED''
           WHERE submission_row.DocumentVersionId = version_row.DocumentVersionId))
    ORDER BY slot_row.SlotCode;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantFinalDocumentIssues
    @SessionTokenSha256 binary(32)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @ApplicationId uniqueidentifier;
    SELECT @ApplicationId = session_row.ApplicationId
    FROM dbo.ApplicantSession AS session_row
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME();
    SELECT DISTINCT CONCAT(''document:'', slot_row.SlotCode) AS UnresolvedItem
    FROM dbo.DocumentSlot AS slot_row
    LEFT JOIN dbo.DocumentVersion AS version_row
      ON version_row.DocumentVersionId = slot_row.ActiveDocumentVersionId
    LEFT JOIN dbo.Document AS document_row
      ON document_row.DocumentId = version_row.DocumentId
     AND document_row.DocumentSlotId = slot_row.DocumentSlotId
    WHERE slot_row.ApplicationId = @ApplicationId
      AND slot_row.ApplicantVisible = 1
      AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
      AND
      (
          slot_row.ApplicantUploadMode <> ''CLOSED''
          OR (slot_row.RequiredForCompletion = 1
              AND slot_row.ActiveDocumentVersionId IS NULL)
          OR EXISTS
             (SELECT 1 FROM dbo.ApplicantDocumentSubmission AS submission_row
              WHERE submission_row.DocumentSlotId = slot_row.DocumentSlotId
                AND submission_row.SubmissionStatus IN (''PENDING'', ''REJECTED'')
                AND NOT EXISTS
                   (SELECT 1 FROM dbo.ApplicantDocumentSubmission AS later_row
                    WHERE later_row.DocumentSlotId = submission_row.DocumentSlotId
                      AND (later_row.SubmittedAtUtc > submission_row.SubmittedAtUtc
                           OR (later_row.SubmittedAtUtc = submission_row.SubmittedAtUtc
                               AND later_row.ApplicantDocumentSubmissionId >
                                   submission_row.ApplicantDocumentSubmissionId))))
          OR (slot_row.ActiveDocumentVersionId IS NOT NULL AND
              (document_row.DocumentId IS NULL
               OR document_row.DocumentType = ''RECOMMENDATION_LETTER''
               OR EXISTS
                  (SELECT 1 FROM dbo.Recommendation AS recommendation_row
                   WHERE recommendation_row.DocumentId = document_row.DocumentId)
               OR NOT
                  (EXISTS
                     (SELECT 1 FROM dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
                      WHERE visible_version.DocumentVersionId =
                            slot_row.ActiveDocumentVersionId)
                   OR EXISTS
                     (SELECT 1 FROM dbo.ApplicantDocumentSubmission AS accepted_submission
                      JOIN dbo.ApplicantDocumentReviewDecision AS decision_row
                        ON decision_row.ApplicantDocumentSubmissionId =
                           accepted_submission.ApplicantDocumentSubmissionId
                       AND decision_row.ReviewDecision = ''ACCEPTED''
                      WHERE accepted_submission.DocumentVersionId =
                            slot_row.ActiveDocumentVersionId))))
      )
    ORDER BY UnresolvedItem;
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
       (SELECT 1 FROM dbo.DocumentSlot AS slot_row
        WHERE slot_row.ApplicationId = @ApplicationId
          AND slot_row.ApplicantVisible = 1
          AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
          AND slot_row.ApplicantUploadMode <> ''CLOSED'')
        THROW 52430, ''An applicant document slot is still open.'', 1;
    IF EXISTS
       (SELECT 1 FROM dbo.ApplicantDocumentSubmission AS submission_row
        WHERE submission_row.ApplicationId = @ApplicationId
          AND submission_row.SubmissionStatus IN (''PENDING'', ''REJECTED'')
          AND NOT EXISTS
              (SELECT 1 FROM dbo.ApplicantDocumentSubmission AS later_row
               WHERE later_row.DocumentSlotId = submission_row.DocumentSlotId
                 AND (later_row.SubmittedAtUtc > submission_row.SubmittedAtUtc
                      OR (later_row.SubmittedAtUtc = submission_row.SubmittedAtUtc
                          AND later_row.ApplicantDocumentSubmissionId >
                              submission_row.ApplicantDocumentSubmissionId))))
        THROW 52431, ''An applicant document submission is unresolved.'', 1;
    IF EXISTS
       (SELECT 1 FROM dbo.DocumentSlot AS slot_row
        WHERE slot_row.ApplicationId = @ApplicationId
          AND slot_row.ApplicantVisible = 1
          AND slot_row.RequiredForCompletion = 1
          AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
          AND slot_row.ActiveDocumentVersionId IS NULL)
        THROW 52432, ''A required applicant document is missing.'', 1;
    IF EXISTS
       (SELECT 1
        FROM dbo.DocumentSlot AS slot_row
        JOIN dbo.DocumentVersion AS version_row
          ON version_row.DocumentVersionId = slot_row.ActiveDocumentVersionId
        JOIN dbo.Document AS document_row
          ON document_row.DocumentId = version_row.DocumentId
         AND document_row.DocumentSlotId = slot_row.DocumentSlotId
        WHERE slot_row.ApplicationId = @ApplicationId
          AND slot_row.ApplicantVisible = 1
          AND (slot_row.SlotCode LIKE ''%RECOMMEND%''
               OR document_row.DocumentType = ''RECOMMENDATION_LETTER''
               OR EXISTS
                  (SELECT 1 FROM dbo.Recommendation AS recommendation_row
                   WHERE recommendation_row.DocumentId = document_row.DocumentId)
               OR NOT
                  (EXISTS
                     (SELECT 1 FROM dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
                      WHERE visible_version.DocumentVersionId = version_row.DocumentVersionId)
                   OR EXISTS
                     (SELECT 1
                      FROM dbo.ApplicantDocumentSubmission AS submission_row
                      JOIN dbo.ApplicantDocumentReviewDecision AS decision_row
                        ON decision_row.ApplicantDocumentSubmissionId =
                           submission_row.ApplicantDocumentSubmissionId
                       AND decision_row.ReviewDecision = ''ACCEPTED''
                      WHERE submission_row.DocumentVersionId = version_row.DocumentVersionId))))
        THROW 52433, ''A confidential document cannot enter applicant finalization.'', 1;
    DECLARE @ExpectedDocuments TABLE
    (
        SlotCode varchar(80) NOT NULL,
        DocumentVersionId uniqueidentifier NOT NULL,
        PlaintextSha256 binary(32) NOT NULL
    );
    INSERT @ExpectedDocuments (SlotCode, DocumentVersionId, PlaintextSha256)
    SELECT slot_row.SlotCode, version_row.DocumentVersionId, object_row.PlaintextSha256
    FROM dbo.DocumentSlot AS slot_row
    JOIN dbo.Document AS document_row
      ON document_row.DocumentSlotId = slot_row.DocumentSlotId
    JOIN dbo.DocumentVersion AS version_row
      ON version_row.DocumentVersionId = slot_row.ActiveDocumentVersionId
     AND version_row.DocumentId = document_row.DocumentId
    JOIN dbo.StoredObject AS object_row
      ON object_row.StoredObjectId = version_row.StoredObjectId
    WHERE slot_row.ApplicationId = @ApplicationId
      AND slot_row.ApplicantVisible = 1
      AND slot_row.SlotCode NOT LIKE ''%RECOMMEND%''
      AND document_row.DocumentType <> ''RECOMMENDATION_LETTER''
      AND NOT EXISTS
          (SELECT 1 FROM dbo.Recommendation AS recommendation_row
           WHERE recommendation_row.DocumentId = document_row.DocumentId)
      AND (EXISTS
          (SELECT 1 FROM dbo.vw_ApplicantVisibleDocumentVersion AS visible_version
           WHERE visible_version.DocumentVersionId = version_row.DocumentVersionId)
       OR EXISTS
          (SELECT 1
           FROM dbo.ApplicantDocumentSubmission AS submission_row
           JOIN dbo.ApplicantDocumentReviewDecision AS decision_row
             ON decision_row.ApplicantDocumentSubmissionId =
                submission_row.ApplicantDocumentSubmissionId
            AND decision_row.ReviewDecision = ''ACCEPTED''
           WHERE submission_row.DocumentVersionId = version_row.DocumentVersionId));
    IF (SELECT COUNT_BIG(*) FROM OPENJSON(@ManifestJson, ''$.documents'')) <>
       (SELECT COUNT_BIG(*) FROM @ExpectedDocuments)
        THROW 52434, ''The applicant-document manifest is incomplete.'', 1;
    IF EXISTS
       (SELECT 1 FROM @ExpectedDocuments AS expected
        WHERE NOT EXISTS
          (SELECT 1 FROM OPENJSON(@ManifestJson, ''$.documents'')
           WITH
           (SlotCode varchar(80) ''$.slotCode'',
            DocumentVersionId uniqueidentifier ''$.documentVersionId'',
            PlaintextSha256 varchar(64) ''$.plaintextSha256'') AS manifest_document
           WHERE manifest_document.SlotCode = expected.SlotCode
             AND manifest_document.DocumentVersionId = expected.DocumentVersionId
             AND expected.PlaintextSha256 =
                 CONVERT(binary(32), manifest_document.PlaintextSha256, 2)))
        THROW 52435, ''An applicant document is missing or stale.'', 1;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ListPendingApplicantDocumentSubmissions
AS
BEGIN
    SET NOCOUNT ON;
    SELECT submission_row.ApplicantDocumentSubmissionId,
           submission_row.ApplicationId, submission_row.DocumentSlotId,
           submission_row.DocumentVersionId, submission_row.SubmittedDisplayName,
           submission_row.SubmittedAtUtc
    FROM dbo.ApplicantDocumentSubmission AS submission_row
    JOIN dbo.Document AS document_row
      ON document_row.DocumentId =
         (SELECT version_row.DocumentId FROM dbo.DocumentVersion AS version_row
          WHERE version_row.DocumentVersionId = submission_row.DocumentVersionId)
    WHERE submission_row.SubmissionStatus = ''PENDING''
      AND document_row.DocumentType <> ''RECOMMENDATION_LETTER''
      AND NOT EXISTS
          (SELECT 1 FROM dbo.Recommendation AS recommendation_row
           WHERE recommendation_row.DocumentId = document_row.DocumentId)
    ORDER BY submission_row.SubmittedAtUtc,
             submission_row.ApplicantDocumentSubmissionId;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ReviewApplicantDocumentSubmission
    @ApplicantDocumentSubmissionId uniqueidentifier, @Decision varchar(12),
    @ReviewedByIdentity nvarchar(255), @ReviewerGroup varchar(40),
    @ReviewReason nvarchar(1000) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @ReviewerGroup NOT IN (''EHF-Administrators'', ''EHF-Trustees'')
       OR NULLIF(LTRIM(RTRIM(@ReviewedByIdentity)), N'''') IS NULL
       OR @Decision NOT IN (''ACCEPTED'', ''REJECTED'')
       OR (@Decision = ''REJECTED'' AND NULLIF(LTRIM(RTRIM(@ReviewReason)), N'''') IS NULL)
        THROW 52652, ''A valid document review is required.'', 1;
    BEGIN TRANSACTION;
    BEGIN TRY
        DECLARE @ApplicationId uniqueidentifier, @DocumentSlotId uniqueidentifier,
                @DocumentVersionId uniqueidentifier;
        SELECT @ApplicationId = submission_row.ApplicationId,
               @DocumentSlotId = submission_row.DocumentSlotId,
               @DocumentVersionId = submission_row.DocumentVersionId
        FROM dbo.ApplicantDocumentSubmission AS submission_row WITH (UPDLOCK, HOLDLOCK)
        JOIN dbo.DocumentVersion AS version_row
          ON version_row.DocumentVersionId = submission_row.DocumentVersionId
        JOIN dbo.Document AS document_row
          ON document_row.DocumentId = version_row.DocumentId
        WHERE submission_row.ApplicantDocumentSubmissionId = @ApplicantDocumentSubmissionId
          AND submission_row.SubmissionStatus = ''PENDING''
          AND document_row.DocumentType <> ''RECOMMENDATION_LETTER''
          AND NOT EXISTS
              (SELECT 1 FROM dbo.Recommendation AS recommendation_row
               WHERE recommendation_row.DocumentId = document_row.DocumentId);
        IF @ApplicationId IS NULL
            THROW 52653, ''The applicant document submission is unavailable.'', 1;
        INSERT dbo.ApplicantDocumentReviewDecision
            (ApplicantDocumentSubmissionId, ReviewDecision, ReviewedByIdentity,
             ReviewerGroup, ReviewReason)
        VALUES
            (@ApplicantDocumentSubmissionId, @Decision, @ReviewedByIdentity,
             @ReviewerGroup, @ReviewReason);
        UPDATE dbo.ApplicantDocumentSubmission
        SET SubmissionStatus = @Decision, ReviewedByIdentity = @ReviewedByIdentity,
            ReviewedAtUtc = SYSUTCDATETIME(), ReviewReason = @ReviewReason
        WHERE ApplicantDocumentSubmissionId = @ApplicantDocumentSubmissionId;
        IF @Decision = ''ACCEPTED''
            UPDATE dbo.DocumentSlot
            SET ActiveDocumentVersionId = @DocumentVersionId
            WHERE DocumentSlotId = @DocumentSlotId AND ApplicationId = @ApplicationId;
        ELSE
            UPDATE dbo.DocumentSlot
            SET ApplicantUploadMode = ''REPLACEMENT'', UploadReason = @ReviewReason,
                OpenedByIdentity = @ReviewedByIdentity, OpenedAtUtc = SYSUTCDATETIME()
            WHERE DocumentSlotId = @DocumentSlotId AND ApplicationId = @ApplicationId;
        SELECT @ApplicantDocumentSubmissionId, @ApplicationId, @Decision,
               @ReviewedByIdentity, ReviewedAtUtc
        FROM dbo.ApplicantDocumentSubmission
        WHERE ApplicantDocumentSubmissionId = @ApplicantDocumentSubmissionId;
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.SubmitApplicantFinalConfirmation
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
        IF @ConfirmationId IS NULL
        BEGIN
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
                FROM (VALUES (''identity''), (''employment''), (''qualifications''),
                             (''publications''), (''contribution''))
                     AS required_section(SectionCode)
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
                     AND CONVERT(bigint, draft_row.RowVersion) = manifest_section.DraftVersion
                    JOIN dbo.ApplicantSectionConfirmation AS confirmation_row
                      ON confirmation_row.ApplicationId = draft_row.ApplicationId
                     AND confirmation_row.SectionCode = draft_row.SectionCode
                     AND confirmation_row.DraftRowVersion = draft_row.RowVersion
                     AND confirmation_row.CanonicalSectionSha256 =
                         CONVERT(binary(32), manifest_section.CanonicalSha256, 2)
                    WHERE manifest_section.SectionCode = required_section.SectionCode
                )
            )
                THROW 52136, ''An applicant section is missing or stale.'', 1;
            EXEC dbo.ValidateApplicantFinalDocuments
                @ApplicationId = @ApplicationId, @ManifestJson = @ManifestJson;
            SET @ConfirmationId = NEWID();
            INSERT dbo.ApplicantFinalConfirmation
                (ApplicantFinalConfirmationId, ApplicationId, ManifestJson,
                 ManifestSha256, ConfirmedByIdentity)
            VALUES
                (@ConfirmationId, @ApplicationId, @ManifestJson,
                 @ManifestSha256, N''APPLICANT'');
            UPDATE dbo.Application
            SET ApplicationStatus = ''IN_REVIEW'', ConfirmedAtUtc = NULL,
                UpdatedAtUtc = SYSUTCDATETIME()
            WHERE ApplicationId = @ApplicationId;
            INSERT dbo.AuditEvent
                (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
            VALUES
                (@ApplicationId, ''APPLICANT_SUBMITTED_FOR_REVIEW'', N''APPLICANT'',
                 ''ApplicantFinalConfirmation'', @ConfirmationId,
                 (SELECT @ApplicationId AS applicationId FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));
        END;
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

EXEC(N'
CREATE PROCEDURE dbo.ListPendingApplicantSubmissions
AS
BEGIN
    SET NOCOUNT ON;
    SELECT confirmation_row.ApplicantFinalConfirmationId,
           confirmation_row.ApplicationId, confirmation_row.ConfirmedAtUtc
    FROM dbo.ApplicantFinalConfirmation AS confirmation_row
    WHERE confirmation_row.SupersededAtUtc IS NULL
      AND NOT EXISTS
          (SELECT 1 FROM dbo.ApplicantFinalReviewDecision AS decision_row
           WHERE decision_row.ApplicantFinalConfirmationId =
                 confirmation_row.ApplicantFinalConfirmationId)
    ORDER BY confirmation_row.ConfirmedAtUtc,
             confirmation_row.ApplicantFinalConfirmationId;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantSubmissionReview
    @ApplicantFinalConfirmationId uniqueidentifier
AS
BEGIN
    SET NOCOUNT ON;
    SELECT confirmation_row.ApplicantFinalConfirmationId,
           confirmation_row.ApplicationId, baseline.ProjectionJson,
           confirmation_row.ManifestJson
    FROM dbo.ApplicantFinalConfirmation AS confirmation_row
    JOIN dbo.ApplicantPortalBaseline AS baseline
      ON baseline.ApplicationId = confirmation_row.ApplicationId
    WHERE confirmation_row.ApplicantFinalConfirmationId = @ApplicantFinalConfirmationId
      AND confirmation_row.SupersededAtUtc IS NULL;
    SELECT draft_row.SectionCode, draft_row.DraftJson
    FROM dbo.ApplicantFinalConfirmation AS confirmation_row
    JOIN dbo.ApplicantSectionDraft AS draft_row
      ON draft_row.ApplicationId = confirmation_row.ApplicationId
    WHERE confirmation_row.ApplicantFinalConfirmationId = @ApplicantFinalConfirmationId
      AND confirmation_row.SupersededAtUtc IS NULL
    ORDER BY draft_row.SectionCode;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.PromoteApprovedApplicantDrafts
    @ApplicationId uniqueidentifier,
    @ApprovedByIdentity nvarchar(255)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @Projection nvarchar(max), @Identity nvarchar(max),
            @Employment nvarchar(max), @Qualifications nvarchar(max),
            @Publications nvarchar(max), @Contribution nvarchar(max);
    SELECT @Projection = ProjectionJson FROM dbo.ApplicantPortalBaseline
    WHERE ApplicationId = @ApplicationId;
    SELECT @Identity = MAX(CASE WHEN SectionCode = ''identity'' THEN DraftJson END),
           @Employment = MAX(CASE WHEN SectionCode = ''employment'' THEN DraftJson END),
           @Qualifications = MAX(CASE WHEN SectionCode = ''qualifications'' THEN DraftJson END),
           @Publications = MAX(CASE WHEN SectionCode = ''publications'' THEN DraftJson END),
           @Contribution = MAX(CASE WHEN SectionCode = ''contribution'' THEN DraftJson END)
    FROM dbo.ApplicantSectionDraft WHERE ApplicationId = @ApplicationId;
    IF @Projection IS NULL OR @Identity IS NULL OR @Employment IS NULL
       OR @Qualifications IS NULL OR @Publications IS NULL OR @Contribution IS NULL
        THROW 52644, ''The approved applicant projection is incomplete.'', 1;
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.fullName'', JSON_VALUE(@Identity, ''$.fullName''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.preferredName'', JSON_VALUE(@Identity, ''$.preferredName''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.registeredEmail'', JSON_VALUE(@Identity, ''$.registeredEmail''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.alternativeEmail'', JSON_VALUE(@Identity, ''$.alternativeEmail''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.telephone'', JSON_VALUE(@Identity, ''$.telephone''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.birthMonth'', TRY_CONVERT(int, JSON_VALUE(@Identity, ''$.birthMonth'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.birthYear'', TRY_CONVERT(int, JSON_VALUE(@Identity, ''$.birthYear'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.gender'', JSON_VALUE(@Identity, ''$.gender''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.genderSelfDescription'', JSON_VALUE(@Identity, ''$.genderSelfDescription''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.institute'', JSON_VALUE(@Employment, ''$.institute''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.principalInvestigator'', JSON_VALUE(@Employment, ''$.principalInvestigator''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.positionTitle'', JSON_VALUE(@Employment, ''$.positionTitle''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.postdoctoralEmploymentStatus'', JSON_VALUE(@Employment, ''$.postdoctoralEmploymentStatus''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.employmentStartDate'', JSON_VALUE(@Employment, ''$.employmentStartDate''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.employmentEndDate'', JSON_VALUE(@Employment, ''$.employmentEndDate''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.futureStartDate'', JSON_VALUE(@Employment, ''$.futureStartDate''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.researchArea'', JSON_VALUE(@Employment, ''$.researchArea''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.clinicalWorkPercent'', TRY_CONVERT(decimal(5,2), JSON_VALUE(@Employment, ''$.clinicalWorkPercent'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.firstAuthorDeclaration'',
        CASE JSON_VALUE(@Employment, ''$.firstAuthorDeclaration'')
             WHEN ''true'' THEN CAST(1 AS bit) WHEN ''false'' THEN CAST(0 AS bit) END);
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.degreeCategory'', JSON_VALUE(@Qualifications, ''$.degreeCategory''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.phdDate'', JSON_VALUE(@Qualifications, ''$.phdDate''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.firstAuthorPaperCount'', TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.firstAuthorPaperCount'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.lastAuthorPaperCount'', TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.lastAuthorPaperCount'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.totalPaperCount'', TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.totalPaperCount'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.hIndex'', TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.hIndex'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.applicantReportedCitationTotal'', TRY_CONVERT(bigint, JSON_VALUE(@Publications, ''$.applicantReportedCitationTotal'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.orcid'', JSON_VALUE(@Publications, ''$.orcid''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.googleScholarProfileUrl'', JSON_VALUE(@Publications, ''$.googleScholarProfileUrl''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.noGoogleScholarProfile'',
        CASE JSON_VALUE(@Publications, ''$.noGoogleScholarProfile'')
             WHEN ''true'' THEN CAST(1 AS bit) WHEN ''false'' THEN CAST(0 AS bit) END);
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.googleScholarCitationTotal'', TRY_CONVERT(bigint, JSON_VALUE(@Publications, ''$.googleScholarCitationTotal'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.contributionStatement'', JSON_VALUE(@Contribution, ''$.contributionStatement''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.locked'', CAST(1 AS bit));
    UPDATE dbo.ApplicantPortalBaseline SET ProjectionJson = @Projection
    WHERE ApplicationId = @ApplicationId;
    DECLARE @ApplicantId uniqueidentifier;
    SELECT @ApplicantId = ApplicantId FROM dbo.Application
    WHERE ApplicationId = @ApplicationId;
    UPDATE dbo.Applicant
    SET PreferredName = JSON_VALUE(@Identity, ''$.preferredName''),
        BirthMonth = TRY_CONVERT(tinyint, JSON_VALUE(@Identity, ''$.birthMonth'')),
        BirthYear = TRY_CONVERT(smallint, JSON_VALUE(@Identity, ''$.birthYear'')),
        SelfReportedGender = JSON_VALUE(@Identity, ''$.gender''),
        UpdatedAtUtc = SYSUTCDATETIME()
    WHERE ApplicantId = @ApplicantId;
    DELETE dbo.ApplicantContact
    WHERE ApplicantId = @ApplicantId
      AND ContactType IN (''REGISTERED_EMAIL'', ''ALTERNATIVE_EMAIL'', ''TELEPHONE'');
    INSERT dbo.ApplicantContact
        (ApplicantId, ContactType, ContactValue, IsPrimary,
         ReviewStatus, ReviewedByIdentity, ReviewedAtUtc)
    SELECT @ApplicantId, contact_value.ContactType,
           contact_value.ContactValue, contact_value.IsPrimary,
           ''REVIEWED'', @ApprovedByIdentity, SYSUTCDATETIME()
    FROM (VALUES
       (''REGISTERED_EMAIL'', JSON_VALUE(@Identity, ''$.registeredEmail''), CAST(1 AS bit)),
       (''ALTERNATIVE_EMAIL'', JSON_VALUE(@Identity, ''$.alternativeEmail''), CAST(0 AS bit)),
       (''TELEPHONE'', JSON_VALUE(@Identity, ''$.telephone''), CAST(0 AS bit))
    ) AS contact_value(ContactType, ContactValue, IsPrimary)
    WHERE NULLIF(LTRIM(RTRIM(contact_value.ContactValue)), N'''') IS NOT NULL;
    UPDATE dbo.EmploymentAffiliation
    SET InstitutionName = JSON_VALUE(@Employment, ''$.institute''),
        PositionTitle = JSON_VALUE(@Employment, ''$.positionTitle''),
        ClinicalWorkPercent = TRY_CONVERT(decimal(5,2),
            JSON_VALUE(@Employment, ''$.clinicalWorkPercent'')),
        UpdatedAtUtc = SYSUTCDATETIME()
    WHERE EmploymentAffiliationId =
       (SELECT TOP (1) EmploymentAffiliationId FROM dbo.EmploymentAffiliation
        WHERE ApplicationId = @ApplicationId ORDER BY EmploymentAffiliationId);
    IF @@ROWCOUNT = 0
        INSERT dbo.EmploymentAffiliation
            (ApplicationId, InstitutionName, PositionTitle, ClinicalWorkPercent)
        VALUES
            (@ApplicationId, JSON_VALUE(@Employment, ''$.institute''),
             JSON_VALUE(@Employment, ''$.positionTitle''),
             TRY_CONVERT(decimal(5,2), JSON_VALUE(@Employment, ''$.clinicalWorkPercent'')));
    DELETE dbo.Qualification WHERE ApplicationId = @ApplicationId;
    INSERT dbo.Qualification (ApplicationId, DegreeType, PhdDate)
    VALUES
       (@ApplicationId, JSON_VALUE(@Qualifications, ''$.degreeCategory''),
        TRY_CONVERT(date, JSON_VALUE(@Qualifications, ''$.phdDate'')));
    MERGE dbo.Bibliometrics AS target
    USING (SELECT @ApplicationId AS ApplicationId) AS source
       ON target.ApplicationId = source.ApplicationId
    WHEN MATCHED THEN UPDATE SET
       FirstAuthorPaperCount = TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.firstAuthorPaperCount'')),
       LastAuthorPaperCount = TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.lastAuthorPaperCount'')),
       TotalPaperCount = TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.totalPaperCount'')),
       UpdatedAtUtc = SYSUTCDATETIME()
    WHEN NOT MATCHED THEN INSERT
       (ApplicationId, FirstAuthorPaperCount, LastAuthorPaperCount,
         TotalPaperCount)
    VALUES
       (@ApplicationId,
        TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.firstAuthorPaperCount'')),
        TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.lastAuthorPaperCount'')),
        TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.totalPaperCount'')));
    MERGE dbo.ContributionStatement AS target
    USING (SELECT @ApplicationId AS ApplicationId,
                  JSON_VALUE(@Contribution, ''$.contributionStatement'') AS StatementText) AS source
       ON target.ApplicationId = source.ApplicationId
    WHEN MATCHED THEN UPDATE SET StatementText = source.StatementText,
       UpdatedAtUtc = SYSUTCDATETIME()
    WHEN NOT MATCHED THEN INSERT (ApplicationId, StatementText)
       VALUES (source.ApplicationId, source.StatementText);
    MERGE dbo.EligibilityDeclaration AS target
    USING (SELECT @ApplicationId AS ApplicationId,
                  ''FIRST_AUTHOR_PUBLICATION'' AS DeclarationCode,
                  CASE JSON_VALUE(@Employment, ''$.firstAuthorDeclaration'')
                    WHEN ''true'' THEN CAST(1 AS bit)
                    WHEN ''false'' THEN CAST(0 AS bit) END AS DeclaredValue) AS source
       ON target.ApplicationId = source.ApplicationId
      AND target.DeclarationCode = source.DeclarationCode
    WHEN MATCHED THEN UPDATE SET DeclaredValue = source.DeclaredValue,
       UpdatedAtUtc = SYSUTCDATETIME()
    WHEN NOT MATCHED THEN INSERT (ApplicationId, DeclarationCode, DeclaredValue)
       VALUES (source.ApplicationId, source.DeclarationCode, source.DeclaredValue);
    DECLARE @PromotedSections TABLE
    (
        ApplicationSectionVersionId uniqueidentifier NOT NULL,
        SectionCode varchar(80) NOT NULL,
        VersionNumber int NOT NULL,
        SnapshotJson nvarchar(max) NOT NULL
    );
    INSERT dbo.ApplicationSectionVersion
        (ApplicationSectionVersionId, ApplicationId, SectionCode,
         VersionNumber, SnapshotJson, ChangedByIdentity)
    OUTPUT inserted.ApplicationSectionVersionId, inserted.SectionCode,
           inserted.VersionNumber, inserted.SnapshotJson
      INTO @PromotedSections
    SELECT NEWID(), @ApplicationId, draft_row.SectionCode,
           ISNULL((SELECT MAX(existing.VersionNumber)
                   FROM dbo.ApplicationSectionVersion AS existing
                   WHERE existing.ApplicationId = @ApplicationId
                     AND existing.SectionCode = draft_row.SectionCode), 0) + 1,
           draft_row.DraftJson, @ApprovedByIdentity
    FROM dbo.ApplicantSectionDraft AS draft_row
    WHERE draft_row.ApplicationId = @ApplicationId;
    INSERT dbo.FieldProvenance
        (ApplicationId, EntityType, EntityId, FieldName, VersionNumber,
         SourceType, SourceIdentifier, ValueSha256, SourceObservedAtUtc)
    SELECT @ApplicationId, ''ApplicationSectionVersion'',
           promoted.ApplicationSectionVersionId, field_row.[key],
           promoted.VersionNumber, ''APPLICANT'',
           CONCAT(N''Approved applicant portal draft:'', promoted.SectionCode),
           HASHBYTES(''SHA2_256'', CONVERT(varbinary(max), field_row.value)),
           SYSUTCDATETIME()
    FROM @PromotedSections AS promoted
    CROSS APPLY OPENJSON(promoted.SnapshotJson) AS field_row;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ApproveApplicantSubmission
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
                 ''ApplicantFinalConfirmation'',
                 @ApplicantFinalConfirmationId,
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
    IF @ActorGroup NOT IN
       (N''EHF-Administrators'', N''EHF-Trustees'')
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
    ORDER BY applicant.LegalFamilyName, applicant.LegalGivenNames;
END;
');

GRANT EXECUTE ON dbo.GetApplicationForEntraApplicant TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.RequestApplicantAccess TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.ListPendingApplicantAccessRequests TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.ReviewApplicantAccessRequest TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.ProvisionApplicantAccessRequest TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.CreateEntraApplicantSession TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetApplicantSession TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetApplicantProjection TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetApplicantSectionDraft TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetApplicantSectionConfirmation TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetApplicantDocumentSlots TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.RegisterApplicantDocumentSubmission TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetApplicantDocumentDownload TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetApplicantFinalDocuments TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetApplicantFinalDocumentIssues TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.ListPendingApplicantDocumentSubmissions TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.ReviewApplicantDocumentSubmission TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.ListPendingApplicantSubmissions TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetApplicantSubmissionReview TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.ApproveApplicantSubmission TO EHFApplicationRuntime;

DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantAccessRequest TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantEntraIdentity TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantPortalBaseline TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantFinalReviewDecision TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantDocumentReviewDecision TO EHFApplicationRuntime;
