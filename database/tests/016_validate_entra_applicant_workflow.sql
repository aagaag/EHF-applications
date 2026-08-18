SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.ApplicantAccessRequest', N'U') IS NULL
    THROW 53600, 'Applicant access requests are missing.', 1;
IF OBJECT_ID(N'dbo.ApplicantEntraIdentity', N'U') IS NULL
    THROW 53601, 'Applicant Entra mappings are missing.', 1;
IF OBJECT_ID(N'dbo.ApplicantPortalBaseline', N'U') IS NULL
    THROW 53602, 'Applicant portal baselines are missing.', 1;
IF OBJECT_ID(N'dbo.ApplicantFinalReviewDecision', N'U') IS NULL
    THROW 53603, 'Applicant final review decisions are missing.', 1;
IF OBJECT_ID(N'dbo.ApplicantDocumentReviewDecision', N'U') IS NULL
    THROW 53608, 'Applicant document review decisions are missing.', 1;
IF OBJECT_ID(N'dbo.CreateEntraApplicantSession', N'P') IS NULL
    THROW 53604, 'Entra applicant session creation is missing.', 1;
IF OBJECT_ID(N'dbo.ApproveApplicantSubmission', N'P') IS NULL
    THROW 53605, 'Applicant approval is missing.', 1;
IF OBJECT_ID(N'dbo.RegisterApplicantDocumentSubmission', N'P') IS NULL
    THROW 53609, 'Applicant document registration is missing.', 1;
IF OBJECT_ID(N'dbo.ReviewApplicantDocumentSubmission', N'P') IS NULL
    THROW 53610, 'Applicant document review is missing.', 1;
IF COL_LENGTH(N'dbo.ApplicantSession', N'EntraObjectId') IS NULL
    THROW 53606, 'Applicant sessions cannot bind Entra identities.', 1;
IF EXISTS
(
    SELECT 1
    FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND class = 1
      AND major_id = OBJECT_ID(N'dbo.ApplicantEntraIdentity', N'U')
      AND permission_name = N'SELECT'
      AND state IN (N'G', N'W')
)
    THROW 53607, 'Runtime table reads must remain denied.', 1;

BEGIN TRANSACTION;
DECLARE @CallId uniqueidentifier = NEWID(),
        @ApplicantId uniqueidentifier = NEWID(),
        @ApplicationId uniqueidentifier = NEWID(),
        @AccessRequestId uniqueidentifier = NEWID(),
        @EntraObjectId uniqueidentifier = NEWID(),
        @SessionHash binary(32) = HASHBYTES('SHA2_256', N'validator-session'),
        @CsrfHash binary(32) = HASHBYTES('SHA2_256', N'validator-csrf'),
        @IdleAt datetime2(7) = DATEADD(hour, 1, SYSUTCDATETIME()),
        @AbsoluteAt datetime2(7) = DATEADD(hour, 2, SYSUTCDATETIME());
INSERT dbo.FellowshipCall
    (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
VALUES
    (@CallId, CONCAT(N'EHF-VALIDATOR-', CONVERT(nvarchar(36), @CallId)),
     N'Entra validator', 'OPEN', DATEADD(day, 90, SYSUTCDATETIME()));
INSERT dbo.Applicant
    (ApplicantId, LegalGivenNames, LegalFamilyName, SelfReportedGender)
VALUES (@ApplicantId, N'Entra', N'Validator', N'Prefer not to say');
INSERT dbo.Application
    (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus)
VALUES (@ApplicationId, @CallId, @ApplicantId, 'IMPORTED');
INSERT dbo.ApplicantPortalBaseline
    (ApplicationId, ProjectionJson, CreatedByIdentity)
VALUES
    (@ApplicationId,
     N'{"applicant":{"locked":false},"sections":{},"documents":[]}',
     N'VALIDATOR');
INSERT dbo.ApplicantAccessRequest
    (ApplicantAccessRequestId, RequestedEmail, RequestedDisplayName)
VALUES
    (@AccessRequestId, N'validator@example.test', N'Entra Validator');
EXEC dbo.ReviewApplicantAccessRequest
    @ApplicantAccessRequestId=@AccessRequestId, @Decision='APPROVED',
    @ReviewedByIdentity=N'VALIDATOR', @ReviewerGroup='EHF-Administrators';
EXEC dbo.ProvisionApplicantAccessRequest
    @ApplicantAccessRequestId=@AccessRequestId,
    @ApplicationId=@ApplicationId, @EntraObjectId=@EntraObjectId,
    @ProvisionedByIdentity=N'VALIDATOR', @ProvisionerGroup='EHF-Administrators';
IF NOT EXISTS
   (SELECT 1 FROM dbo.ApplicantEntraIdentity
    WHERE ApplicationId=@ApplicationId AND EntraObjectId=@EntraObjectId
      AND ApplicantAccessRequestId=@AccessRequestId
      AND IdentityKind='APPLICANT' AND Enabled=1)
    THROW 53617, 'Approved access was not atomically bound to its application.', 1;
EXEC dbo.CreateEntraApplicantSession
    @EntraObjectId=@EntraObjectId, @SessionTokenSha256=@SessionHash,
    @CsrfTokenSha256=@CsrfHash,
    @IdleExpiresAtUtc=@IdleAt,
    @AbsoluteExpiresAtUtc=@AbsoluteAt;
UPDATE dbo.ApplicantEntraIdentity
SET Enabled=0, DisabledAtUtc=SYSUTCDATETIME()
WHERE EntraObjectId=@EntraObjectId;
DECLARE @DisabledSession TABLE
(
    ApplicationId uniqueidentifier, CsrfTokenSha256 binary(32),
    IdleExpiresAtUtc datetime2(7), AbsoluteExpiresAtUtc datetime2(7),
    ApplicantInvitationId uniqueidentifier, EntraObjectId uniqueidentifier
);
INSERT @DisabledSession
EXEC dbo.GetApplicantSession
    @SessionTokenSha256=@SessionHash,
    @IdleExpiresAtUtc=@IdleAt;
IF EXISTS (SELECT 1 FROM @DisabledSession)
    THROW 53611, 'A disabled Entra identity retained an applicant session.', 1;
INSERT dbo.Bibliometrics
    (ApplicationId, GoogleScholarCitationCount)
VALUES (@ApplicationId, 999);
INSERT dbo.ApplicantSectionDraft
    (ApplicationId, SectionCode, DraftJson, SavedByIdentity)
VALUES
    (@ApplicationId, 'identity',
     N'{"fullName":"Approved Name","preferredName":"Approved","registeredEmail":"approved@example.test","alternativeEmail":null,"telephone":"+41 71 000 00 00","birthMonth":6,"birthYear":1988,"gender":"Prefer not to say","genderSelfDescription":null}', N'APPLICANT'),
    (@ApplicationId, 'employment',
     N'{"institute":"Approved Institute","principalInvestigator":"PI","positionTitle":"Postdoc","postdoctoralEmploymentStatus":"EMPLOYED","employmentStartDate":"2025-01-01","employmentEndDate":null,"futureStartDate":null,"researchArea":"Biology","clinicalWorkPercent":0,"firstAuthorDeclaration":true}', N'APPLICANT'),
    (@ApplicationId, 'qualifications',
     N'{"degreeCategory":"PHD","phdDate":"2024-01-01"}', N'APPLICANT'),
    (@ApplicationId, 'publications',
     N'{"firstAuthorPaperCount":4,"lastAuthorPaperCount":2,"totalPaperCount":9,"hIndex":7,"applicantReportedCitationTotal":300,"orcid":"0000-0000-0000-0001","googleScholarProfileUrl":null,"noGoogleScholarProfile":true,"googleScholarCitationTotal":301}', N'APPLICANT'),
    (@ApplicationId, 'contribution',
     N'{"contributionStatement":"An approved scientific contribution."}', N'APPLICANT');
EXEC dbo.PromoteApprovedApplicantDrafts
     @ApplicationId=@ApplicationId, @ApprovedByIdentity=N'VALIDATOR';
IF NOT EXISTS
   (SELECT 1 FROM dbo.Applicant
    WHERE ApplicantId=@ApplicantId AND PreferredName=N'Approved'
      AND BirthMonth=6 AND BirthYear=1988)
    THROW 53612, 'Approved identity fields were not promoted.', 1;
IF NOT EXISTS
   (SELECT 1 FROM dbo.Bibliometrics
    WHERE ApplicationId=@ApplicationId AND FirstAuthorPaperCount=4
      AND LastAuthorPaperCount=2 AND TotalPaperCount=9
      AND GoogleScholarCitationCount=999)
    THROW 53613, 'Approved bibliometrics were not promoted.', 1;
IF NOT EXISTS
   (SELECT 1 FROM dbo.EmploymentAffiliation
    WHERE ApplicationId=@ApplicationId AND ClinicalWorkPercent=0)
    THROW 53618, 'Zero clinical-work percentage was not promoted.', 1;
IF NOT EXISTS
   (SELECT 1 FROM dbo.ContributionStatement
    WHERE ApplicationId=@ApplicationId
      AND StatementText=N'An approved scientific contribution.')
    THROW 53614, 'The contribution statement was not promoted.', 1;
IF (SELECT COUNT(*) FROM dbo.ApplicationSectionVersion
    WHERE ApplicationId=@ApplicationId AND ChangedByIdentity=N'VALIDATOR') <> 5
    THROW 53615, 'Approved section versions were not preserved.', 1;
IF NOT EXISTS
   (SELECT 1 FROM dbo.FieldProvenance
    WHERE ApplicationId=@ApplicationId AND SourceType='APPLICANT')
    THROW 53616, 'Approved field provenance was not recorded.', 1;
ROLLBACK TRANSACTION;

PRINT 'PASS 016 Entra applicant workflow';
