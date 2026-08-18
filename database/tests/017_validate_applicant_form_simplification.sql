SET NOCOUNT ON;
SET XACT_ABORT ON;
SET QUOTED_IDENTIFIER ON;

IF COL_LENGTH('dbo.Qualification', 'ConferralDate') IS NULL
    THROW 53700, 'Qualification conferral date is missing.', 1;

IF OBJECT_DEFINITION(OBJECT_ID('dbo.CK_Qualification_DegreeType')) NOT LIKE '%BSC%'
   OR OBJECT_DEFINITION(OBJECT_ID('dbo.CK_Qualification_DegreeType')) NOT LIKE '%MA%'
    THROW 53701, 'Qualification degree types were not extended.', 1;

DECLARE @PromotionDefinition nvarchar(max) =
    OBJECT_DEFINITION(OBJECT_ID('dbo.PromoteApprovedApplicantDrafts'));
IF @PromotionDefinition NOT LIKE '%OPENJSON(@Degrees)%'
   OR @PromotionDefinition NOT LIKE '%ConferralDate%'
   OR @PromotionDefinition NOT LIKE '%FieldProvenance%'
   OR @PromotionDefinition NOT LIKE '%WHEN ''employed'' THEN CAST(1 AS bit)%'
   OR @PromotionDefinition NOT LIKE '%WHEN ''future'' THEN CAST(0 AS bit)%'
   OR @PromotionDefinition NOT LIKE '%THROW 52646%'
    THROW 53702, 'Applicant promotion does not use the simplified schema.', 1;

DECLARE @MetricsDefinition nvarchar(max) =
    OBJECT_DEFINITION(OBJECT_ID('dbo.GetInternalApplicationMetrics'));
IF @MetricsDefinition NOT LIKE '%PhdConferralDate%'
   OR @MetricsDefinition NOT LIKE '%DATEDIFF(%'
   OR @MetricsDefinition NOT LIKE '%ApplicationDeadlineUtc%'
   OR @MetricsDefinition NOT LIKE '%$.phdDate%'
   OR @MetricsDefinition NOT LIKE '%MD_PHD%'
    THROW 53707, 'Academic age is not derived from the PhD conferral date.', 1;

DECLARE @CompatibilityDefinition nvarchar(max) =
    OBJECT_DEFINITION(OBJECT_ID('dbo.TR_ApplicantSectionDraft_V17Compatibility'));
IF @CompatibilityDefinition NOT LIKE '%$.degrees%'
   OR @CompatibilityDefinition NOT LIKE '%$.publications%'
   OR @CompatibilityDefinition NOT LIKE '%requires the current portal version%'
    THROW 53708, 'Rollback compatibility protection is missing.', 1;

DECLARE @SaveDefinition nvarchar(max) =
    OBJECT_DEFINITION(OBJECT_ID('dbo.SaveApplicantSectionDraft'));
IF @SaveDefinition NOT LIKE '%Merge a v16 qualifications write%'
   OR @SaveDefinition NOT LIKE '%JSON_QUERY(@BeforeJson, ''$.degrees'')%'
   OR @SaveDefinition NOT LIKE '%JSON_QUERY(@BeforeJson, ''$.publications'')%'
   OR @SaveDefinition NOT LIKE '%HAVING COUNT_BIG(*) > 1%'
   OR @SaveDefinition NOT LIKE '%ApplicantFieldCorrection%'
    THROW 53709, 'Rolling v16/v17 draft merge compatibility is missing.', 1;

IF OBJECT_ID(N'dbo.ReturnApplicantSubmissionForCorrection', N'P') IS NULL
    THROW 53710, 'The bounded applicant correction procedure is missing.', 1;
IF HAS_PERMS_BY_NAME(N'dbo.ReturnApplicantSubmissionForCorrection', N'OBJECT', N'EXECUTE') <> 1
    THROW 53711, 'The runtime cannot execute the bounded applicant correction procedure.', 1;

DECLARE @DraftReadDefinition nvarchar(max) =
    OBJECT_DEFINITION(OBJECT_ID('dbo.GetApplicantSectionDraftV17')),
        @ConfirmationReadDefinition nvarchar(max) =
    OBJECT_DEFINITION(OBJECT_ID('dbo.GetApplicantSectionConfirmation')),
        @ConfirmDefinition nvarchar(max) =
    OBJECT_DEFINITION(OBJECT_ID('dbo.ConfirmApplicantSection'));
IF @DraftReadDefinition NOT LIKE '%ApplicantReopenScope%'
   OR @DraftReadDefinition NOT LIKE '%Reason%'
    THROW 53712, 'Returned-section instructions are not exposed to the applicant.', 1;
IF @ConfirmationReadDefinition NOT LIKE '%ConfirmedAtUtc <= open_scope.ReopenedAtUtc%'
   OR @ConfirmDefinition NOT LIKE '%@StoredDraftSavedAtUtc <= open_scope.ReopenedAtUtc%'
   OR @ConfirmDefinition NOT LIKE '%THROW 52143%'
   OR @ConfirmDefinition NOT LIKE '%THROW 52144%'
    THROW 53713, 'Returned sections are not forced through save and reconfirmation.', 1;
IF OBJECT_ID(N'dbo.TR_ApplicantFinalConfirmation_ReopenValidation', N'TR') IS NULL
    THROW 53714, 'Returned-section finalization validation is missing.', 1;
IF OBJECT_DEFINITION(
       OBJECT_ID('dbo.TR_ApplicantFinalConfirmation_ReopenValidation'))
   NOT LIKE '%SET ClosedAtUtc = SYSUTCDATETIME()%'
    THROW 53716, 'Final resubmission does not close reopened applicant scopes.', 1;

BEGIN TRANSACTION;

DECLARE @CallId uniqueidentifier = NEWID(),
        @ApplicantId uniqueidentifier = NEWID(),
        @ApplicationId uniqueidentifier = NEWID();

INSERT dbo.FellowshipCall
    (FellowshipCallId, CallCode, DisplayName, CallStatus,
     ApplicationDeadlineUtc)
VALUES
    (@CallId, N'EHF-017-VALIDATOR', N'Synthetic release 017 validator',
     'OPEN', DATEADD(day, 30, SYSUTCDATETIME()));

INSERT dbo.Applicant
    (ApplicantId, LegalGivenNames, LegalFamilyName)
VALUES
    (@ApplicantId, N'Synthetic', N'Simplification');

INSERT dbo.Application
    (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus)
VALUES
    (@ApplicationId, @CallId, @ApplicantId, 'IN_REVIEW');

INSERT dbo.ApplicantPortalBaseline
    (ApplicationId, ProjectionJson, CreatedByIdentity)
VALUES
    (@ApplicationId,
     N'{"applicant":{"genderSelfDescription":"legacy","degreeCategory":"PHD","phdDate":"2020-01-01","noGoogleScholarProfile":true,"googleScholarCitationTotal":999},"sections":{},"documents":[]}',
     N'VALIDATOR');

INSERT dbo.Bibliometrics
    (ApplicationId, GoogleScholarCitationCount)
VALUES
    (@ApplicationId, 999);

INSERT dbo.ApplicantSectionDraft
    (ApplicationId, SectionCode, DraftJson, SavedByIdentity)
VALUES
    (@ApplicationId, 'identity',
     N'{"fullName":"Approved Name","preferredName":"Approved","registeredEmail":"approved@example.test","alternativeEmail":null,"telephone":"+41 71 000 00 00","birthMonth":6,"birthYear":1988,"gender":"Prefer not to say"}',
     N'APPLICANT'),
    (@ApplicationId, 'employment',
     N'{"institute":"Approved Institute","principalInvestigator":"PI","positionTitle":"Postdoc","postdoctoralEmploymentStatus":true,"employmentStartDate":"2025-01-01","employmentEndDate":"2027-12-31","futureStartDate":null,"researchArea":"Biology","clinicalWorkPercent":0,"firstAuthorDeclaration":true}',
     N'APPLICANT'),
    (@ApplicationId, 'qualifications',
     N'{"degrees":[{"degreeType":"BSc","conferralDate":"2014-06-30"},{"degreeType":"PhD","conferralDate":"2020-01-01"}]}',
     N'APPLICANT'),
    (@ApplicationId, 'publications',
     N'{"firstAuthorPaperCount":4,"lastAuthorPaperCount":2,"totalPaperCount":9,"hIndex":7,"applicantReportedCitationTotal":300,"orcid":"0000-0000-0000-0001","hasGoogleScholarProfile":false,"googleScholarProfileUrl":null,"publications":[{"doi":"10.1000/example","confirmed":true}]}',
     N'APPLICANT'),
    (@ApplicationId, 'contribution',
     N'{"contributionStatement":"An approved scientific contribution."}',
     N'APPLICANT');

EXEC dbo.PromoteApprovedApplicantDrafts
     @ApplicationId = @ApplicationId,
     @ApprovedByIdentity = N'VALIDATOR';

IF (SELECT COUNT(*) FROM dbo.Qualification
    WHERE ApplicationId = @ApplicationId) <> 2
   OR NOT EXISTS
      (SELECT 1 FROM dbo.Qualification
       WHERE ApplicationId = @ApplicationId
         AND DegreeType = 'BSC' AND ConferralDate = '2014-06-30'
         AND PhdDate IS NULL)
   OR NOT EXISTS
      (SELECT 1 FROM dbo.Qualification
       WHERE ApplicationId = @ApplicationId
         AND DegreeType = 'PHD' AND ConferralDate = '2020-01-01'
         AND PhdDate = '2020-01-01')
    THROW 53703, 'Repeatable degrees were not promoted.', 1;

DECLARE @Projection nvarchar(max) =
    (SELECT ProjectionJson FROM dbo.ApplicantPortalBaseline
     WHERE ApplicationId = @ApplicationId);
IF JSON_QUERY(@Projection, '$.applicant.degrees') IS NULL
   OR JSON_QUERY(@Projection, '$.applicant.publications') IS NULL
   OR JSON_VALUE(@Projection, '$.applicant.hasGoogleScholarProfile') <> 'false'
   OR JSON_VALUE(@Projection, '$.applicant.genderSelfDescription') IS NOT NULL
   OR JSON_VALUE(@Projection, '$.applicant.googleScholarCitationTotal') IS NOT NULL
    THROW 53704, 'Simplified applicant projection was not promoted.', 1;

IF NOT EXISTS
   (SELECT 1 FROM dbo.Bibliometrics
    WHERE ApplicationId = @ApplicationId
      AND GoogleScholarCitationCount = 999)
    THROW 53705, 'Verified Google Scholar citations were overwritten.', 1;

IF (SELECT COUNT(*) FROM dbo.ApplicationSectionVersion
    WHERE ApplicationId = @ApplicationId
      AND ChangedByIdentity = N'VALIDATOR') <> 5
   OR NOT EXISTS
      (SELECT 1 FROM dbo.FieldProvenance
       WHERE ApplicationId = @ApplicationId
         AND SourceType='APPLICANT')
    THROW 53706, 'Approved applicant provenance was not preserved.', 1;

ROLLBACK TRANSACTION;

BEGIN TRANSACTION;
DECLARE @CorrectionCallId uniqueidentifier = NEWID(),
        @CorrectionApplicantId uniqueidentifier = NEWID(),
        @CorrectionApplicationId uniqueidentifier = NEWID(),
        @CorrectionConfirmationId uniqueidentifier = NEWID(),
        @CorrectionDraftJson nvarchar(max) =
            N'{"postdoctoralEmploymentStatus":true}',
        @CorrectionManifest nvarchar(max) =
            N'{"schemaVersion":1,"sections":[],"documents":[]}';
INSERT dbo.FellowshipCall
    (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
VALUES
    (@CorrectionCallId, N'EHF-017-CORRECTION', N'Correction workflow validator',
     'OPEN', DATEADD(day, 30, SYSUTCDATETIME()));
INSERT dbo.Applicant
    (ApplicantId, LegalGivenNames, LegalFamilyName)
VALUES
    (@CorrectionApplicantId, N'Synthetic', N'Correction');
INSERT dbo.Application
    (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus, ConfirmedAtUtc)
VALUES
    (@CorrectionApplicationId, @CorrectionCallId, @CorrectionApplicantId,
     'CONFIRMED', SYSUTCDATETIME());
INSERT dbo.ApplicantSectionDraft
    (ApplicationId, SectionCode, DraftJson, SavedByIdentity)
VALUES
    (@CorrectionApplicationId, 'employment', @CorrectionDraftJson, N'APPLICANT');
DECLARE @CorrectionDraftRowVersion binary(8) =
        (SELECT RowVersion FROM dbo.ApplicantSectionDraft
         WHERE ApplicationId = @CorrectionApplicationId
           AND SectionCode = 'employment'),
        @CorrectionDraftHash binary(32) =
        HASHBYTES('SHA2_256', CONVERT(varbinary(max), @CorrectionDraftJson));
INSERT dbo.ApplicantSectionConfirmation
    (ApplicationId, SectionCode, CanonicalSectionSha256,
     DraftRowVersion, ConfirmedByIdentity)
VALUES
    (@CorrectionApplicationId, 'employment', @CorrectionDraftHash,
     @CorrectionDraftRowVersion, N'APPLICANT');
INSERT dbo.ApplicantFinalConfirmation
    (ApplicantFinalConfirmationId, ApplicationId, ManifestJson,
     ManifestSha256, ConfirmedByIdentity)
VALUES
    (@CorrectionConfirmationId, @CorrectionApplicationId, @CorrectionManifest,
     HASHBYTES('SHA2_256', CONVERT(varbinary(max), @CorrectionManifest)), N'APPLICANT');

EXEC dbo.ReturnApplicantSubmissionForCorrection
     @ApplicantFinalConfirmationId = @CorrectionConfirmationId,
     @SectionCode = 'employment',
     @Reason = N'Please clarify the employment answer.',
     @ReviewedByIdentity = N'VALIDATOR',
     @ReviewerGroup = 'EHF-Administrators';

IF NOT EXISTS
   (SELECT 1 FROM dbo.ApplicantFinalReviewDecision
    WHERE ApplicantFinalConfirmationId = @CorrectionConfirmationId
      AND ReviewDecision = 'REJECTED')
   OR NOT EXISTS
   (SELECT 1 FROM dbo.ApplicantReopenScope
    WHERE ApplicationId = @CorrectionApplicationId
      AND ScopeType = 'SECTION' AND ScopeCode = 'employment'
      AND Reason = N'Please clarify the employment answer.'
      AND ClosedAtUtc IS NULL)
   OR EXISTS
   (SELECT 1 FROM dbo.ApplicantFinalConfirmation
    WHERE ApplicantFinalConfirmationId = @CorrectionConfirmationId
      AND SupersededAtUtc IS NULL)
    THROW 53715, 'The applicant correction workflow did not reopen exactly one section.', 1;

DECLARE @ReopenedAtUtc datetime2(7) =
    (SELECT ReopenedAtUtc FROM dbo.ApplicantReopenScope
     WHERE ApplicationId = @CorrectionApplicationId
       AND ScopeType = 'SECTION' AND ScopeCode = 'employment'
       AND ClosedAtUtc IS NULL),
        @CorrectedDraftJson nvarchar(max) =
            N'{"postdoctoralEmploymentStatus":false}';
UPDATE dbo.ApplicantSectionDraft
SET DraftJson = @CorrectedDraftJson,
    SavedAtUtc = DATEADD(millisecond, 10, @ReopenedAtUtc)
WHERE ApplicationId = @CorrectionApplicationId
  AND SectionCode = 'employment';
DECLARE @CorrectedDraftRowVersion binary(8) =
        (SELECT RowVersion FROM dbo.ApplicantSectionDraft
         WHERE ApplicationId = @CorrectionApplicationId
           AND SectionCode = 'employment'),
        @CorrectedDraftHash binary(32) =
        HASHBYTES('SHA2_256', CONVERT(varbinary(max), @CorrectedDraftJson));
INSERT dbo.ApplicantSectionConfirmation
    (ApplicationId, SectionCode, CanonicalSectionSha256,
     DraftRowVersion, ConfirmedByIdentity, ConfirmedAtUtc)
VALUES
    (@CorrectionApplicationId, 'employment', @CorrectedDraftHash,
     @CorrectedDraftRowVersion, N'APPLICANT',
     DATEADD(millisecond, 20, @ReopenedAtUtc));

DECLARE @CorrectedManifest nvarchar(max) =
    N'{"schemaVersion":1,"sections":[{"section":"employment","rowVersion":'
    + CONVERT(nvarchar(30), CONVERT(bigint, @CorrectedDraftRowVersion))
    + N',"canonicalSha256":"'
    + CONVERT(varchar(64), @CorrectedDraftHash, 2)
    + N'"}],"documents":[]}';
INSERT dbo.ApplicantFinalConfirmation
    (ApplicationId, ManifestJson, ManifestSha256, ConfirmedByIdentity)
VALUES
    (@CorrectionApplicationId, @CorrectedManifest,
     HASHBYTES('SHA2_256', CONVERT(varbinary(max), @CorrectedManifest)),
     N'APPLICANT');

IF EXISTS
   (SELECT 1 FROM dbo.ApplicantReopenScope
    WHERE ApplicationId = @CorrectionApplicationId
      AND ClosedAtUtc IS NULL)
    THROW 53717, 'Final resubmission did not close the correction scope.', 1;

DECLARE @CorrectionEntraObjectId uniqueidentifier = NEWID(),
        @CorrectionSessionHash binary(32) =
            HASHBYTES('SHA2_256', CONVERT(varbinary(max), NEWID())),
        @CorrectionCsrfHash binary(32) =
            HASHBYTES('SHA2_256', CONVERT(varbinary(max), NEWID()));
INSERT dbo.ApplicantEntraIdentity
    (ApplicationId, EntraObjectId, IdentityKind, Enabled, LinkedByIdentity)
VALUES
    (@CorrectionApplicationId, @CorrectionEntraObjectId,
     'SYNTHETIC_TEST', 1, N'VALIDATOR');
INSERT dbo.ApplicantSession
    (ApplicantInvitationId, ApplicationId, EntraObjectId,
     SessionTokenSha256, CsrfTokenSha256, IdleExpiresAtUtc, AbsoluteExpiresAtUtc)
VALUES
    (NULL, @CorrectionApplicationId, @CorrectionEntraObjectId,
     @CorrectionSessionHash, @CorrectionCsrfHash,
     DATEADD(hour, 1, SYSUTCDATETIME()), DATEADD(hour, 2, SYSUTCDATETIME()));
UPDATE dbo.Application
SET ApplicationStatus = 'IN_REVIEW', ConfirmedAtUtc = NULL
WHERE ApplicationId = @CorrectionApplicationId;

DECLARE @PostSubmitSaveLocked bit = 0;
BEGIN TRY
    EXEC dbo.SaveApplicantSectionDraft
         @SessionTokenSha256 = @CorrectionSessionHash,
         @SectionCode = 'employment',
         @DraftJson = N'{"postdoctoralEmploymentStatus":true}',
         @ExpectedRowVersion = @CorrectedDraftRowVersion;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() IN (52025, 52027)
        SET @PostSubmitSaveLocked = 1;
    ELSE
        THROW;
END CATCH;
IF @PostSubmitSaveLocked = 0
    THROW 53718, 'A corrected section remained editable after final resubmission.', 1;
IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;

PRINT 'PASS 017 applicant form simplification';
