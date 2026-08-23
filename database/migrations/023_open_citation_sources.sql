SET NOCOUNT ON;
SET XACT_ABORT ON;

ALTER TABLE dbo.PublicationCitationObservation
    DROP CONSTRAINT CK_PublicationCitationObservation_Source;
ALTER TABLE dbo.PublicationCitationObservation
    ADD CONSTRAINT CK_PublicationCitationObservation_Source CHECK
        (SourceCode IN
            ('GOOGLE_SCHOLAR', 'BIORXIV', 'MEDRXIV', 'OPENALEX', 'SEMANTIC_SCHOLAR'));

EXEC(N'
ALTER PROCEDURE dbo.GetApplicantPreview
    @ApplicationId uniqueidentifier,
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128),
    @EmitResult bit = 1,
    @EmitDrafts bit = 1,
    @EmitPublications bit = 0
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
        SELECT @ApplicationId AS ApplicationId, @ApplicantName AS ApplicantName,
               @ApplicationStatus AS ApplicationStatus, @ProjectionJson AS ProjectionJson;

    IF @EmitDrafts = 1
        SELECT draft_row.SectionCode, draft_row.DraftJson
        FROM dbo.ApplicantSectionDraft AS draft_row
        WHERE draft_row.ApplicationId = @ApplicationId
        ORDER BY draft_row.SectionCode;

    IF @EmitPublications = 1
        SELECT publication_row.ApplicationPublicationId,
               publication_row.AuthorsText,
               publication_row.Title,
               publication_row.JournalText,
               publication_row.VolumeText,
               publication_row.PagesText,
               publication_row.PublicationYear,
               scholar.CitationCount,
               scholar.CitationStatus,
               publication_row.Doi,
               openalex.CitationCount AS OpenAlexCitationCount,
               openalex.CitationStatus AS OpenAlexCitationStatus,
               semantic_scholar.CitationCount AS SemanticScholarCitationCount,
               semantic_scholar.CitationStatus AS SemanticScholarCitationStatus
        FROM dbo.ApplicationPublication AS publication_row
        OUTER APPLY
        (
            SELECT TOP (1) observation.CitationCount, observation.CitationStatus
            FROM dbo.PublicationCitationObservation AS observation
            WHERE observation.ApplicationPublicationId = publication_row.ApplicationPublicationId
              AND observation.SourceCode = ''GOOGLE_SCHOLAR''
            ORDER BY CASE WHEN observation.ObservedAtUtc IS NULL THEN 1 ELSE 0 END,
                     observation.ObservedAtUtc DESC,
                     observation.RecordedAtUtc DESC,
                     observation.PublicationCitationObservationId DESC
        ) AS scholar
        OUTER APPLY
        (
            SELECT TOP (1) observation.CitationCount, observation.CitationStatus
            FROM dbo.PublicationCitationObservation AS observation
            WHERE observation.ApplicationPublicationId = publication_row.ApplicationPublicationId
              AND observation.SourceCode = ''OPENALEX''
            ORDER BY CASE WHEN observation.ObservedAtUtc IS NULL THEN 1 ELSE 0 END,
                     observation.ObservedAtUtc DESC,
                     observation.RecordedAtUtc DESC,
                     observation.PublicationCitationObservationId DESC
        ) AS openalex
        OUTER APPLY
        (
            SELECT TOP (1) observation.CitationCount, observation.CitationStatus
            FROM dbo.PublicationCitationObservation AS observation
            WHERE observation.ApplicationPublicationId = publication_row.ApplicationPublicationId
              AND observation.SourceCode = ''SEMANTIC_SCHOLAR''
            ORDER BY CASE WHEN observation.ObservedAtUtc IS NULL THEN 1 ELSE 0 END,
                     observation.ObservedAtUtc DESC,
                     observation.RecordedAtUtc DESC,
                     observation.PublicationCitationObservationId DESC
        ) AS semantic_scholar
        WHERE publication_row.ApplicationId = @ApplicationId
        ORDER BY publication_row.PublicationYear DESC,
                 publication_row.Title,
                 publication_row.ApplicationPublicationId;
END;
');

GRANT EXECUTE ON dbo.GetApplicantPreview TO EHFApplicationRuntime;
