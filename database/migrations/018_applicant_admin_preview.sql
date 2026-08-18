SET NOCOUNT ON;
SET XACT_ABORT ON;

EXEC(N'
CREATE PROCEDURE dbo.ListApplicantPreviews
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
    ORDER BY ApplicantName, application_row.ApplicationId;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantPreview
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

GRANT EXECUTE ON dbo.ListApplicantPreviews TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetApplicantPreview TO EHFApplicationRuntime;
