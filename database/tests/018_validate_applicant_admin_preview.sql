SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.ListApplicantPreviews', N'P') IS NULL
    THROW 52820, 'ListApplicantPreviews is missing.', 1;
IF OBJECT_ID(N'dbo.GetApplicantPreview', N'P') IS NULL
    THROW 52821, 'GetApplicantPreview is missing.', 1;

BEGIN TRY
    EXEC dbo.ListApplicantPreviews @ActorGroup=N'EHF-Trustees';
    THROW 52822, 'Trustee preview listing was not rejected.', 1;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() <> 52810 THROW;
END CATCH;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallId uniqueidentifier = '18000000-0000-4000-8000-000000000001';
    DECLARE @ApplicantId uniqueidentifier = '18000000-0000-4000-8000-000000000002';
    DECLARE @ApplicationId uniqueidentifier = '18000000-0000-4000-8000-000000000003';
    DECLARE @OtherApplicantId uniqueidentifier = '18000000-0000-4000-8000-000000000004';
    DECLARE @OtherApplicationId uniqueidentifier = '18000000-0000-4000-8000-000000000005';

    INSERT dbo.FellowshipCall
        (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
    VALUES
        (@CallId, N'EHF-018-VALIDATION', N'Preview validation', 'DRAFT', '2027-01-31');
    INSERT dbo.Applicant
        (ApplicantId, LegalGivenNames, LegalFamilyName)
    VALUES
        (@ApplicantId, N'Synthetic', N'Preview'),
        (@OtherApplicantId, N'Synthetic Other', N'Preview');
    INSERT dbo.Application
        (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus)
    VALUES
        (@ApplicationId, @CallId, @ApplicantId, 'IMPORTED'),
        (@OtherApplicationId, @CallId, @OtherApplicantId, 'IMPORTED');
    INSERT dbo.ApplicantPortalBaseline
        (ApplicationId, ProjectionJson, CreatedByIdentity)
    VALUES
        (@ApplicationId,
         N'{"applicant":{"fullName":"Synthetic Preview","registeredEmail":"synthetic@example.test"}}',
         N'validator'),
        (@OtherApplicationId,
         N'{"applicant":{"fullName":"Synthetic Other Preview","registeredEmail":"synthetic-other@example.test"}}',
         N'validator');
    INSERT dbo.ApplicantSectionDraft
        (ApplicationId, SectionCode, DraftJson, SavedByIdentity)
    VALUES
        (@ApplicationId, 'identity',
         N'{"fullName":"Synthetic Updated Preview","telephone":"+41 00 000 00 00"}',
         N'validator');

    DECLARE @PreviewList TABLE
    (
        ApplicationId uniqueidentifier,
        ApplicantName nvarchar(401),
        ApplicationStatus varchar(20)
    );
    INSERT @PreviewList
    EXEC dbo.ListApplicantPreviews @ActorGroup=N'EHF-Administrators';
    IF NOT EXISTS
       (SELECT 1 FROM @PreviewList
        WHERE ApplicationId=@ApplicationId
          AND ApplicantName=N'Synthetic Updated Preview'
          AND ApplicationStatus='IMPORTED')
        THROW 52823, 'The administrator preview list did not return the saved record.', 1;
    IF NOT EXISTS
       (SELECT 1 FROM @PreviewList
        WHERE ApplicationId=@OtherApplicationId
          AND ApplicantName=N'Synthetic Other Preview')
        THROW 52826, 'The administrator preview list omitted another portal record.', 1;

    DECLARE @PreviewHeader TABLE
    (
        ApplicationId uniqueidentifier,
        ApplicantName nvarchar(401),
        ApplicationStatus varchar(20),
        ProjectionJson nvarchar(max)
    );
    INSERT @PreviewHeader
    EXEC dbo.GetApplicantPreview
        @ApplicationId=@ApplicationId,
        @ActorIdentity=N'cloudflare:validator',
        @ActorGroup=N'EHF-Administrators',
        @EmitResult=1,
        @EmitDrafts=0;
    IF (SELECT COUNT_BIG(*) FROM @PreviewHeader) <> 1
       OR NOT EXISTS
          (SELECT 1 FROM @PreviewHeader
           WHERE ApplicationId=@ApplicationId
             AND ApplicantName=N'Synthetic Updated Preview'
             AND JSON_VALUE(ProjectionJson, '$.applicant.fullName')=N'Synthetic Preview')
        THROW 52827, 'The exact requested applicant preview was not returned.', 1;
    IF NOT EXISTS
       (SELECT 1 FROM dbo.AuditEvent
        WHERE ApplicationId=@ApplicationId
          AND EventType='APPLICANT_PREVIEW_OPENED'
          AND ActorIdentity=N'cloudflare:validator'
          AND EntityId=@ApplicationId)
        THROW 52824, 'Opening an applicant preview was not audited.', 1;

    BEGIN TRY
        EXEC dbo.GetApplicantPreview
            @ApplicationId='18000000-0000-4000-8000-000000000099',
            @ActorIdentity=N'cloudflare:validator',
            @ActorGroup=N'EHF-Administrators',
            @EmitResult=0;
        THROW 52825, 'An unknown application preview was not rejected.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() <> 52811 THROW;
    END CATCH;

    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 018 applicant administrator preview';
