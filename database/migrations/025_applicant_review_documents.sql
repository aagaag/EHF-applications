SET NOCOUNT ON;
SET XACT_ABORT ON;

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
           application_row.ApplicationStatus,
           COALESCE(
               TRY_CONVERT(
                   decimal(8,2),
                   DATEDIFF(day, academic_degree.PhdConferralDate,
                       TRY_CONVERT(date, call_row.ApplicationDeadlineUtc)) / 365.2425
               ),
               TRY_CONVERT(decimal(8,2), JSON_VALUE(
                   legacy_section.SnapshotJson, ''$.academic_age_observation''))
           ) AS AcademicAgeYears,
           COALESCE(
               TRY_CONVERT(int, JSON_VALUE(baseline.ProjectionJson, ''$.applicant.hIndex'')),
               TRY_CONVERT(int, JSON_VALUE(legacy_section.SnapshotJson, ''$.h_index'')),
               profile_observation.HIndex
           ) AS HIndex,
           COALESCE(
               profile_observation.CitationCount,
               TRY_CONVERT(bigint, JSON_VALUE(
                   baseline.ProjectionJson, ''$.applicant.applicantReportedCitationTotal'')),
               TRY_CONVERT(bigint, JSON_VALUE(
                   legacy_section.SnapshotJson, ''$.total_citations'')),
               bibliometrics.GoogleScholarCitationCount
           ) AS CitationCount,
           profile_observation.SourceCode AS CitationSource,
           profile_observation.ProfileUrl AS CitationProfileUrl,
           COALESCE(
               NULLIF(JSON_VALUE(baseline.ProjectionJson, ''$.applicant.researchArea''), N''''),
               NULLIF(JSON_VALUE(employment_section.SnapshotJson, ''$.researchArea''), N''''),
               NULLIF(JSON_VALUE(legacy_section.SnapshotJson, ''$.researchArea''), N'''')
           ) AS ResearchArea,
           (
               SELECT COUNT_BIG(*)
               FROM dbo.DocumentSlot AS document_slot
               JOIN dbo.Document AS document_row
                 ON document_row.DocumentSlotId = document_slot.DocumentSlotId
               WHERE document_slot.ApplicationId = application_row.ApplicationId
                 AND document_slot.ActiveDocumentVersionId IS NOT NULL
           ) AS DocumentCount
    FROM dbo.ApplicantPortalBaseline AS baseline
    JOIN dbo.Application AS application_row
      ON application_row.ApplicationId = baseline.ApplicationId
    JOIN dbo.FellowshipCall AS call_row
      ON call_row.FellowshipCallId = application_row.FellowshipCallId
    JOIN dbo.Applicant AS applicant
      ON applicant.ApplicantId = application_row.ApplicantId
    LEFT JOIN dbo.Bibliometrics AS bibliometrics
      ON bibliometrics.ApplicationId = application_row.ApplicationId
    OUTER APPLY
    (
        SELECT TOP (1) draft_row.DraftJson
        FROM dbo.ApplicantSectionDraft AS draft_row
        WHERE draft_row.ApplicationId = application_row.ApplicationId
          AND draft_row.SectionCode = ''identity''
    ) AS identity_draft
    OUTER APPLY
    (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion
     WHERE ApplicationId = application_row.ApplicationId AND SectionCode = ''employment''
     ORDER BY VersionNumber DESC) AS employment_section
    OUTER APPLY
    (SELECT TOP (1) SnapshotJson FROM dbo.ApplicationSectionVersion
     WHERE ApplicationId = application_row.ApplicationId
       AND SectionCode = ''LEGACY_REGISTER_OBSERVATIONS''
     ORDER BY VersionNumber DESC) AS legacy_section
    OUTER APPLY
    (
        SELECT COALESCE(
            (SELECT MIN(TRY_CONVERT(date, JSON_VALUE(degree_row.value, ''$.conferralDate'')))
             FROM OPENJSON(baseline.ProjectionJson, ''$.applicant.degrees'') AS degree_row
             WHERE JSON_VALUE(degree_row.value, ''$.degreeType'') = ''PhD''),
            CASE WHEN JSON_VALUE(baseline.ProjectionJson, ''$.applicant.degreeCategory'')
                      IN (''PHD'', ''MD_PHD'')
                 THEN TRY_CONVERT(date, JSON_VALUE(baseline.ProjectionJson, ''$.applicant.phdDate'')) END,
            (SELECT MIN(COALESCE(qualification.ConferralDate, qualification.PhdDate))
             FROM dbo.Qualification AS qualification
             WHERE qualification.ApplicationId = application_row.ApplicationId
               AND qualification.DegreeType IN (''PHD'', ''MD_PHD''))
        ) AS PhdConferralDate
    ) AS academic_degree
    OUTER APPLY
    (
        SELECT TOP (1) observation.CitationCount, observation.SourceCode,
               observation.ProfileUrl, observation.HIndex
        FROM dbo.ApplicantCitationProfileObservation AS observation
        WHERE observation.ApplicationId = application_row.ApplicationId
        ORDER BY observation.ObservedAtUtc DESC, observation.RecordedAtUtc DESC,
                 observation.ApplicantCitationProfileObservationId DESC
    ) AS profile_observation
    WHERE NOT EXISTS
    (
        SELECT 1 FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
        WHERE workspace_row.ApplicationId = application_row.ApplicationId
    )
    ORDER BY ApplicantName, application_row.ApplicationId;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ListApplicantPreviewDocuments
    @ApplicationId uniqueidentifier,
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @ActorGroup <> N''EHF-Administrators''
       OR LEN(LTRIM(RTRIM(@ActorIdentity))) = 0
        THROW 52920, ''Administrator authorization is required.'', 1;
    IF NOT EXISTS
    (
        SELECT 1 FROM dbo.ApplicantPortalBaseline AS baseline
        WHERE baseline.ApplicationId = @ApplicationId
    )
        THROW 52921, ''The applicant documents are unavailable.'', 1;
    IF EXISTS
    (
        SELECT 1 FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
        WHERE workspace_row.ApplicationId = @ApplicationId
    )
        THROW 52921, ''The applicant documents are unavailable.'', 1;

    INSERT dbo.AuditEvent
        (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
    VALUES
        (@ApplicationId, ''APPLICANT_PREVIEW_DOCUMENTS_OPENED'',
         LTRIM(RTRIM(@ActorIdentity)), ''Application'', @ApplicationId,
         (SELECT @ActorGroup AS actorGroup FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));

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
    WHERE baseline.ApplicationId = @ApplicationId;

    SELECT version_row.DocumentVersionId, document_slot.SlotCode,
           document_slot.SlotLabel, document_row.DocumentType,
           version_row.Classification, stored_object.PageCount,
           stored_object.ByteSize, stored_object.MediaType,
           stored_object.ScanResult, stored_object.ScanSignature,
           version_row.CreatedAtUtc
    FROM dbo.DocumentSlot AS document_slot
    JOIN dbo.Document AS document_row
      ON document_row.DocumentSlotId = document_slot.DocumentSlotId
    JOIN dbo.DocumentVersion AS version_row
      ON version_row.DocumentId = document_row.DocumentId
     AND version_row.DocumentVersionId = document_slot.ActiveDocumentVersionId
    JOIN dbo.StoredObject AS stored_object
      ON stored_object.StoredObjectId = version_row.StoredObjectId
    WHERE document_slot.ApplicationId = @ApplicationId
      AND stored_object.ScanResult = ''CLEAN''
    ORDER BY document_row.DocumentType, document_slot.SlotCode;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantPreviewDocument
    @DocumentVersionId uniqueidentifier,
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @ActorGroup <> N''EHF-Administrators''
       OR LEN(LTRIM(RTRIM(@ActorIdentity))) = 0
        THROW 52920, ''Administrator authorization is required.'', 1;

    DECLARE @ApplicationId uniqueidentifier;
    SELECT @ApplicationId = document_slot.ApplicationId
    FROM dbo.DocumentSlot AS document_slot
    JOIN dbo.Document AS document_row
      ON document_row.DocumentSlotId = document_slot.DocumentSlotId
    JOIN dbo.DocumentVersion AS version_row
      ON version_row.DocumentId = document_row.DocumentId
     AND version_row.DocumentVersionId = document_slot.ActiveDocumentVersionId
    JOIN dbo.StoredObject AS stored_object
      ON stored_object.StoredObjectId = version_row.StoredObjectId
    WHERE document_slot.ActiveDocumentVersionId = @DocumentVersionId
      AND stored_object.ScanResult = ''CLEAN''
      AND NOT EXISTS
      (
          SELECT 1 FROM dbo.ApplicantSyntheticWorkspace AS workspace_row
          WHERE workspace_row.ApplicationId = document_slot.ApplicationId
      );
    IF @ApplicationId IS NULL
        THROW 52921, ''The applicant document is unavailable.'', 1;

    INSERT dbo.AuditEvent
        (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
    VALUES
        (@ApplicationId, ''APPLICANT_PREVIEW_DOCUMENT_OPENED'',
         LTRIM(RTRIM(@ActorIdentity)), ''DocumentVersion'', @DocumentVersionId,
         (SELECT @ActorGroup AS actorGroup FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));

    SELECT document_slot.ApplicationId, document_row.DocumentId,
           version_row.DocumentVersionId, stored_object.StoredObjectId,
           stored_object.ObjectKey, stored_object.KeyVersion,
           stored_object.EnvelopeVersion, stored_object.AesGcmNonce,
           stored_object.PlaintextSha256, stored_object.CiphertextSha256,
           stored_object.ByteSize, stored_object.MediaType,
           stored_object.PageCount, document_slot.SlotCode,
           document_row.DocumentType
    FROM dbo.DocumentSlot AS document_slot
    JOIN dbo.Document AS document_row
      ON document_row.DocumentSlotId = document_slot.DocumentSlotId
    JOIN dbo.DocumentVersion AS version_row
      ON version_row.DocumentId = document_row.DocumentId
     AND version_row.DocumentVersionId = document_slot.ActiveDocumentVersionId
    JOIN dbo.StoredObject AS stored_object
      ON stored_object.StoredObjectId = version_row.StoredObjectId
    WHERE document_slot.ActiveDocumentVersionId = @DocumentVersionId
      AND document_slot.ApplicationId = @ApplicationId
      AND stored_object.ScanResult = ''CLEAN'';
END;
');

GRANT EXECUTE ON dbo.ListApplicantPreviews TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.ListApplicantPreviewDocuments TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetApplicantPreviewDocument TO EHFApplicationRuntime;
