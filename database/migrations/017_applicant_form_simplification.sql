SET NOCOUNT ON;
SET XACT_ABORT ON;

ALTER TABLE dbo.Qualification
    ADD ConferralDate date NULL;

EXEC(N'
UPDATE dbo.Qualification
SET ConferralDate = PhdDate
WHERE ConferralDate IS NULL
  AND PhdDate IS NOT NULL;
');

ALTER TABLE dbo.Qualification
    DROP CONSTRAINT CK_Qualification_DegreeType;

ALTER TABLE dbo.Qualification
    ADD CONSTRAINT CK_Qualification_DegreeType CHECK
        (DegreeType IN ('BSC', 'MA', 'MD', 'PHD', 'MD_PHD', 'OTHER'));

ALTER TABLE dbo.ApplicantSectionConfirmation
    DROP CONSTRAINT UQ_ApplicantSectionConfirmation_Version;

ALTER TABLE dbo.ApplicantSectionConfirmation
    ADD CONSTRAINT UQ_ApplicantSectionConfirmation_Version UNIQUE
        (ApplicationId, SectionCode, CanonicalSectionSha256, DraftRowVersion);

/* Historical one-shot rewrite intentionally disabled.
   Release 017 is an expand-compatible release: existing JSON, including every
   signed and superseded artifact, is preserved byte-for-byte. The application
   presents legacy JSON through the new schema and writes dual-format JSON until
   a later release can remove rollback compatibility safely.
UPDATE baseline
SET ProjectionJson =
    JSON_MODIFY(
    JSON_MODIFY(
    JSON_MODIFY(
    JSON_MODIFY(
    JSON_MODIFY(
    JSON_MODIFY(
    JSON_MODIFY(
    JSON_MODIFY(
    JSON_MODIFY(baseline.ProjectionJson,
        '$.applicant.degrees', JSON_QUERY(degree_json.DegreesJson)),
        '$.applicant.hasGoogleScholarProfile',
        CASE
          WHEN NULLIF(LTRIM(RTRIM(JSON_VALUE(baseline.ProjectionJson,
               '$.applicant.googleScholarProfileUrl'))), N'') IS NOT NULL
            THEN CAST(1 AS bit)
          WHEN JSON_VALUE(baseline.ProjectionJson,
               '$.applicant.noGoogleScholarProfile') = 'true'
            THEN CAST(0 AS bit)
          ELSE NULL
        END),
        '$.applicant.publications', JSON_QUERY(N'[]')),
        '$.applicant.genderSelfDescription', NULL),
        '$.applicant.degreeCategory', NULL),
        '$.applicant.phdDate', NULL),
        '$.applicant.noGoogleScholarProfile', NULL),
        '$.applicant.googleScholarCitationTotal', NULL),
        '$.applicant.postdoctoralEmploymentStatus',
        CASE LOWER(JSON_VALUE(baseline.ProjectionJson,
             '$.applicant.postdoctoralEmploymentStatus'))
          WHEN 'true' THEN CAST(1 AS bit)
          WHEN 'false' THEN CAST(0 AS bit)
          WHEN 'employed' THEN CAST(1 AS bit)
          WHEN 'current' THEN CAST(1 AS bit)
          ELSE NULL
        END)
FROM dbo.ApplicantPortalBaseline AS baseline
CROSS APPLY
(
    SELECT
    (
        SELECT mapped.degreeType, mapped.conferralDate
        FROM
        (
            SELECT degree_value.degreeType, degree_value.conferralDate
            FROM dbo.Qualification AS qualification
            CROSS APPLY
            (
                VALUES
                (
                    CASE qualification.DegreeType
                      WHEN 'BSC' THEN 'BSc' WHEN 'MA' THEN 'MA'
                      WHEN 'MD' THEN 'MD' WHEN 'PHD' THEN 'PhD'
                      WHEN 'MD_PHD' THEN 'MD' END,
                    CASE WHEN qualification.DegreeType = 'MD_PHD' THEN NULL
                         ELSE qualification.PhdDate END
                ),
                (
                    CASE WHEN qualification.DegreeType = 'MD_PHD'
                         THEN 'PhD' END,
                    CASE WHEN qualification.DegreeType = 'MD_PHD'
                         THEN qualification.PhdDate END
                )
            ) AS degree_value(degreeType, conferralDate)
            WHERE qualification.ApplicationId = baseline.ApplicationId
              AND degree_value.degreeType IS NOT NULL
            UNION ALL
            SELECT legacy_value.degreeType, legacy_value.conferralDate
            FROM
            (
                VALUES
                (
                    CASE JSON_VALUE(baseline.ProjectionJson,
                         '$.applicant.degreeCategory')
                      WHEN 'MD' THEN 'MD' WHEN 'PHD' THEN 'PhD'
                      WHEN 'MD_PHD' THEN 'MD' END,
                    CASE WHEN JSON_VALUE(baseline.ProjectionJson,
                              '$.applicant.degreeCategory') = 'PHD'
                         THEN TRY_CONVERT(date, JSON_VALUE(
                              baseline.ProjectionJson, '$.applicant.phdDate')) END
                ),
                (
                    CASE WHEN JSON_VALUE(baseline.ProjectionJson,
                              '$.applicant.degreeCategory') = 'MD_PHD'
                         THEN 'PhD' END,
                    CASE WHEN JSON_VALUE(baseline.ProjectionJson,
                              '$.applicant.degreeCategory') = 'MD_PHD'
                         THEN TRY_CONVERT(date, JSON_VALUE(
                              baseline.ProjectionJson, '$.applicant.phdDate')) END
                )
            ) AS legacy_value(degreeType, conferralDate)
            WHERE NOT EXISTS
                (SELECT 1 FROM dbo.Qualification AS existing
                 WHERE existing.ApplicationId = baseline.ApplicationId)
              AND legacy_value.degreeType IS NOT NULL
        ) AS mapped
        FOR JSON PATH, INCLUDE_NULL_VALUES
    ) AS DegreesJson
) AS degree_json
WHERE NOT EXISTS
(
    SELECT 1
    FROM dbo.ApplicantFinalConfirmation AS final_confirmation
    WHERE final_confirmation.ApplicationId = baseline.ApplicationId
      AND final_confirmation.SupersededAtUtc IS NULL
);

UPDATE draft_row
SET DraftJson = JSON_MODIFY(draft_row.DraftJson,
                            '$.genderSelfDescription', NULL)
FROM dbo.ApplicantSectionDraft AS draft_row
WHERE draft_row.SectionCode = 'identity'
  AND NOT EXISTS
      (SELECT 1 FROM dbo.ApplicantFinalConfirmation AS final_confirmation
       WHERE final_confirmation.ApplicationId = draft_row.ApplicationId
         AND final_confirmation.SupersededAtUtc IS NULL);

UPDATE draft_row
SET DraftJson = JSON_MODIFY(draft_row.DraftJson,
    '$.postdoctoralEmploymentStatus',
    CASE LOWER(JSON_VALUE(draft_row.DraftJson,
         '$.postdoctoralEmploymentStatus'))
      WHEN 'true' THEN CAST(1 AS bit)
      WHEN 'false' THEN CAST(0 AS bit)
      WHEN 'employed' THEN CAST(1 AS bit)
      WHEN 'current' THEN CAST(1 AS bit)
      ELSE NULL
    END)
FROM dbo.ApplicantSectionDraft AS draft_row
WHERE draft_row.SectionCode = 'employment'
  AND NOT EXISTS
      (SELECT 1 FROM dbo.ApplicantFinalConfirmation AS final_confirmation
       WHERE final_confirmation.ApplicationId = draft_row.ApplicationId
         AND final_confirmation.SupersededAtUtc IS NULL);

UPDATE draft_row
SET DraftJson =
    JSON_MODIFY(
    JSON_MODIFY(
    JSON_MODIFY(draft_row.DraftJson,
        '$.degrees', JSON_QUERY(COALESCE(
            JSON_QUERY(draft_row.DraftJson, '$.degrees'),
            degree_json.DegreesJson, N'[]'))),
        '$.degreeCategory', NULL),
        '$.phdDate', NULL)
FROM dbo.ApplicantSectionDraft AS draft_row
CROSS APPLY
(
    SELECT
    (
        SELECT degree_value.degreeType, degree_value.conferralDate
        FROM
        (
            VALUES
            (
                CASE JSON_VALUE(draft_row.DraftJson, '$.degreeCategory')
                  WHEN 'MD' THEN 'MD' WHEN 'PHD' THEN 'PhD'
                  WHEN 'MD_PHD' THEN 'MD' END,
                CASE WHEN JSON_VALUE(draft_row.DraftJson,
                          '$.degreeCategory') = 'PHD'
                     THEN TRY_CONVERT(date, JSON_VALUE(
                          draft_row.DraftJson, '$.phdDate')) END
            ),
            (
                CASE WHEN JSON_VALUE(draft_row.DraftJson,
                          '$.degreeCategory') = 'MD_PHD'
                     THEN 'PhD' END,
                CASE WHEN JSON_VALUE(draft_row.DraftJson,
                          '$.degreeCategory') = 'MD_PHD'
                     THEN TRY_CONVERT(date, JSON_VALUE(
                          draft_row.DraftJson, '$.phdDate')) END
            )
        ) AS degree_value(degreeType, conferralDate)
        WHERE degree_value.degreeType IS NOT NULL
        FOR JSON PATH, INCLUDE_NULL_VALUES
    ) AS DegreesJson
) AS degree_json
WHERE draft_row.SectionCode = 'qualifications'
  AND NOT EXISTS
      (SELECT 1 FROM dbo.ApplicantFinalConfirmation AS final_confirmation
       WHERE final_confirmation.ApplicationId = draft_row.ApplicationId
         AND final_confirmation.SupersededAtUtc IS NULL);

UPDATE draft_row
SET DraftJson =
    JSON_MODIFY(
    JSON_MODIFY(
    JSON_MODIFY(
    JSON_MODIFY(draft_row.DraftJson,
        '$.hasGoogleScholarProfile',
        CASE
          WHEN JSON_VALUE(draft_row.DraftJson,
               '$.hasGoogleScholarProfile') = 'true' THEN CAST(1 AS bit)
          WHEN JSON_VALUE(draft_row.DraftJson,
               '$.hasGoogleScholarProfile') = 'false' THEN CAST(0 AS bit)
          WHEN NULLIF(LTRIM(RTRIM(JSON_VALUE(draft_row.DraftJson,
               '$.googleScholarProfileUrl'))), N'') IS NOT NULL THEN CAST(1 AS bit)
          WHEN JSON_VALUE(draft_row.DraftJson,
               '$.noGoogleScholarProfile') = 'true' THEN CAST(0 AS bit)
          ELSE NULL
        END),
        '$.publications', JSON_QUERY(COALESCE(
            JSON_QUERY(draft_row.DraftJson, '$.publications'), N'[]'))),
        '$.noGoogleScholarProfile', NULL),
        '$.googleScholarCitationTotal', NULL)
FROM dbo.ApplicantSectionDraft AS draft_row
WHERE draft_row.SectionCode = 'publications'
  AND NOT EXISTS
      (SELECT 1 FROM dbo.ApplicantFinalConfirmation AS final_confirmation
       WHERE final_confirmation.ApplicationId = draft_row.ApplicationId
         AND final_confirmation.SupersededAtUtc IS NULL);
*/

-- Expand only records with no section or final confirmation history. Legacy
-- keys remain alongside v17 keys so the currently running v16 binary and a
-- deployment rollback can read the same values without invalidating hashes.
UPDATE baseline
SET ProjectionJson =
    JSON_MODIFY(
    JSON_MODIFY(
    JSON_MODIFY(baseline.ProjectionJson,
        '$.applicant.degrees', JSON_QUERY(COALESCE(
            JSON_QUERY(baseline.ProjectionJson, '$.applicant.degrees'),
            degree_json.DegreesJson, N'[]'))),
        '$.applicant.hasGoogleScholarProfile',
        CASE
          WHEN JSON_VALUE(baseline.ProjectionJson,
               '$.applicant.hasGoogleScholarProfile') = 'true' THEN CAST(1 AS bit)
          WHEN JSON_VALUE(baseline.ProjectionJson,
               '$.applicant.hasGoogleScholarProfile') = 'false' THEN CAST(0 AS bit)
          WHEN NULLIF(LTRIM(RTRIM(JSON_VALUE(baseline.ProjectionJson,
               '$.applicant.googleScholarProfileUrl'))), N'') IS NOT NULL
            THEN CAST(1 AS bit)
          WHEN JSON_VALUE(baseline.ProjectionJson,
               '$.applicant.noGoogleScholarProfile') = 'true' THEN CAST(0 AS bit)
          ELSE NULL
        END),
        '$.applicant.publications', JSON_QUERY(COALESCE(
            JSON_QUERY(baseline.ProjectionJson, '$.applicant.publications'), N'[]')))
FROM dbo.ApplicantPortalBaseline AS baseline
CROSS APPLY
(
    SELECT
    (
        SELECT degree_value.degreeType, degree_value.conferralDate
        FROM
        (
            VALUES
            (
                CASE JSON_VALUE(baseline.ProjectionJson,
                     '$.applicant.degreeCategory')
                  WHEN 'MD' THEN 'MD' WHEN 'PHD' THEN 'PhD'
                  WHEN 'MD_PHD' THEN 'MD' END,
                CASE WHEN JSON_VALUE(baseline.ProjectionJson,
                          '$.applicant.degreeCategory') = 'PHD'
                     THEN TRY_CONVERT(date, JSON_VALUE(
                          baseline.ProjectionJson, '$.applicant.phdDate')) END
            ),
            (
                CASE WHEN JSON_VALUE(baseline.ProjectionJson,
                          '$.applicant.degreeCategory') = 'MD_PHD'
                     THEN 'PhD' END,
                CASE WHEN JSON_VALUE(baseline.ProjectionJson,
                          '$.applicant.degreeCategory') = 'MD_PHD'
                     THEN TRY_CONVERT(date, JSON_VALUE(
                          baseline.ProjectionJson, '$.applicant.phdDate')) END
            )
        ) AS degree_value(degreeType, conferralDate)
        WHERE degree_value.degreeType IS NOT NULL
        FOR JSON PATH, INCLUDE_NULL_VALUES
    ) AS DegreesJson
) AS degree_json
WHERE NOT EXISTS
      (SELECT 1 FROM dbo.ApplicantFinalConfirmation AS final_confirmation
       WHERE final_confirmation.ApplicationId = baseline.ApplicationId)
  AND NOT EXISTS
      (SELECT 1 FROM dbo.ApplicantSectionConfirmation AS section_confirmation
       WHERE section_confirmation.ApplicationId = baseline.ApplicationId);

UPDATE draft_row
SET DraftJson = JSON_MODIFY(
    draft_row.DraftJson,
    '$.degrees',
    JSON_QUERY(COALESCE(
        JSON_QUERY(draft_row.DraftJson, '$.degrees'),
        degree_json.DegreesJson, N'[]')))
FROM dbo.ApplicantSectionDraft AS draft_row
CROSS APPLY
(
    SELECT
    (
        SELECT degree_value.degreeType, degree_value.conferralDate
        FROM
        (
            VALUES
            (
                CASE JSON_VALUE(draft_row.DraftJson, '$.degreeCategory')
                  WHEN 'MD' THEN 'MD' WHEN 'PHD' THEN 'PhD'
                  WHEN 'MD_PHD' THEN 'MD' END,
                CASE WHEN JSON_VALUE(draft_row.DraftJson,
                          '$.degreeCategory') = 'PHD'
                     THEN TRY_CONVERT(date, JSON_VALUE(
                          draft_row.DraftJson, '$.phdDate')) END
            ),
            (
                CASE WHEN JSON_VALUE(draft_row.DraftJson,
                          '$.degreeCategory') = 'MD_PHD'
                     THEN 'PhD' END,
                CASE WHEN JSON_VALUE(draft_row.DraftJson,
                          '$.degreeCategory') = 'MD_PHD'
                     THEN TRY_CONVERT(date, JSON_VALUE(
                          draft_row.DraftJson, '$.phdDate')) END
            )
        ) AS degree_value(degreeType, conferralDate)
        WHERE degree_value.degreeType IS NOT NULL
        FOR JSON PATH, INCLUDE_NULL_VALUES
    ) AS DegreesJson
) AS degree_json
WHERE draft_row.SectionCode = 'qualifications'
  AND NOT EXISTS
      (SELECT 1 FROM dbo.ApplicantFinalConfirmation AS final_confirmation
       WHERE final_confirmation.ApplicationId = draft_row.ApplicationId)
  AND NOT EXISTS
      (SELECT 1 FROM dbo.ApplicantSectionConfirmation AS section_confirmation
       WHERE section_confirmation.ApplicationId = draft_row.ApplicationId);

UPDATE draft_row
SET DraftJson =
    JSON_MODIFY(
    JSON_MODIFY(draft_row.DraftJson,
        '$.hasGoogleScholarProfile',
        CASE
          WHEN JSON_VALUE(draft_row.DraftJson,
               '$.hasGoogleScholarProfile') = 'true' THEN CAST(1 AS bit)
          WHEN JSON_VALUE(draft_row.DraftJson,
               '$.hasGoogleScholarProfile') = 'false' THEN CAST(0 AS bit)
          WHEN NULLIF(LTRIM(RTRIM(JSON_VALUE(draft_row.DraftJson,
               '$.googleScholarProfileUrl'))), N'') IS NOT NULL THEN CAST(1 AS bit)
          WHEN JSON_VALUE(draft_row.DraftJson,
               '$.noGoogleScholarProfile') = 'true' THEN CAST(0 AS bit)
          ELSE NULL
        END),
        '$.publications', JSON_QUERY(COALESCE(
            JSON_QUERY(draft_row.DraftJson, '$.publications'), N'[]')))
FROM dbo.ApplicantSectionDraft AS draft_row
WHERE draft_row.SectionCode = 'publications'
  AND NOT EXISTS
      (SELECT 1 FROM dbo.ApplicantFinalConfirmation AS final_confirmation
       WHERE final_confirmation.ApplicationId = draft_row.ApplicationId)
  AND NOT EXISTS
      (SELECT 1 FROM dbo.ApplicantSectionConfirmation AS section_confirmation
       WHERE section_confirmation.ApplicationId = draft_row.ApplicationId);

EXEC(N'
CREATE TRIGGER dbo.TR_ApplicantSectionDraft_V17Compatibility
ON dbo.ApplicantSectionDraft
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS
    (
        SELECT 1
        FROM inserted AS new_row
        JOIN deleted AS old_row
          ON old_row.ApplicantSectionDraftId = new_row.ApplicantSectionDraftId
        WHERE
          (new_row.SectionCode = ''qualifications''
           AND JSON_QUERY(old_row.DraftJson, ''$.degrees'') IS NOT NULL
           AND JSON_QUERY(new_row.DraftJson, ''$.degrees'') IS NULL)
          OR
          (new_row.SectionCode = ''publications''
           AND (JSON_QUERY(old_row.DraftJson, ''$.publications'') IS NOT NULL
                OR JSON_VALUE(old_row.DraftJson,
                              ''$.hasGoogleScholarProfile'') IS NOT NULL)
           AND (JSON_QUERY(new_row.DraftJson, ''$.publications'') IS NULL
                OR JSON_VALUE(new_row.DraftJson,
                              ''$.hasGoogleScholarProfile'') IS NULL))
    )
        THROW 52027, ''This application section requires the current portal version.'', 1;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.SaveApplicantSectionDraft
    @SessionTokenSha256 binary(32),
    @SectionCode varchar(80),
    @DraftJson nvarchar(max),
    @ExpectedRowVersion binary(8) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF NULLIF(LTRIM(RTRIM(@SectionCode)), '''') IS NULL
        THROW 52021, ''An applicant section is required.'', 1;
    IF @SectionCode NOT IN
       (''identity'', ''employment'', ''qualifications'', ''publications'', ''contribution'')
        THROW 52023, ''The applicant section is invalid.'', 1;
    IF ISJSON(@DraftJson) <> 1
        THROW 52022, ''The applicant draft must be valid JSON.'', 1;
    BEGIN TRANSACTION;
    BEGIN TRY
        DECLARE @ApplicationId uniqueidentifier, @BeforeJson nvarchar(max),
                @ActualRowVersion binary(8), @Status varchar(20);
        SELECT @ApplicationId = session_row.ApplicationId,
               @Status = application_row.ApplicationStatus
        FROM dbo.ApplicantSession AS session_row WITH (UPDLOCK, HOLDLOCK)
        JOIN dbo.Application AS application_row WITH (UPDLOCK, HOLDLOCK)
          ON application_row.ApplicationId = session_row.ApplicationId
        WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
          AND session_row.RevokedAtUtc IS NULL
          AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
          AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME();
        IF @Status IS NULL THROW 52024, ''The application is unavailable.'', 1;
        IF @Status = ''CONFIRMED'' THROW 52025, ''The application is locked.'', 1;
        IF EXISTS
        (
            SELECT 1 FROM dbo.ApplicantFinalConfirmation
            WHERE ApplicationId = @ApplicationId
        )
        AND NOT EXISTS
        (
            SELECT 1 FROM dbo.ApplicantReopenScope
            WHERE ApplicationId = @ApplicationId
              AND ScopeType = ''SECTION''
              AND ScopeCode = @SectionCode
              AND ClosedAtUtc IS NULL
        )
            THROW 52027, ''The application section is locked.'', 1;

        SELECT @BeforeJson = DraftJson, @ActualRowVersion = RowVersion
        FROM dbo.ApplicantSectionDraft WITH (UPDLOCK, HOLDLOCK)
        WHERE ApplicationId = @ApplicationId AND SectionCode = @SectionCode;
        IF @ActualRowVersion IS NOT NULL AND
           (@ExpectedRowVersion IS NULL OR @ExpectedRowVersion <> @ActualRowVersion)
            THROW 52026, ''The applicant draft changed before this update.'', 1;
        IF @ActualRowVersion IS NULL AND @ExpectedRowVersion IS NOT NULL
            THROW 52026, ''The applicant draft changed before this update.'', 1;

        -- Merge a v16 qualifications write into any existing v17 array. This
        -- retains BSc/MA rows that v16 cannot represent and updates MD/PhD rows.
        IF @SectionCode = ''qualifications''
           AND JSON_QUERY(@BeforeJson, ''$.degrees'') IS NOT NULL
           AND JSON_QUERY(@DraftJson, ''$.degrees'') IS NULL
        BEGIN
            IF EXISTS
            (
                SELECT 1
                FROM OPENJSON(@BeforeJson, ''$.degrees'') AS existing
                WHERE JSON_VALUE(existing.value, ''$.degreeType'') IN (''MD'', ''PhD'')
                GROUP BY JSON_VALUE(existing.value, ''$.degreeType'')
                HAVING COUNT_BIG(*) > 1
            )
                THROW 52027, ''This application section requires the current portal version.'', 1;
            DECLARE @LegacyDegreeCategory nvarchar(20) =
                JSON_VALUE(@DraftJson, ''$.degreeCategory''),
                    @MergedDegrees nvarchar(max);
            IF @LegacyDegreeCategory IN (''MD'', ''PHD'', ''MD_PHD'')
            BEGIN
                SET @MergedDegrees =
                (
                    SELECT merged.degreeType, merged.conferralDate
                    FROM
                    (
                        SELECT JSON_VALUE(existing.value, ''$.degreeType'') AS degreeType,
                               JSON_VALUE(existing.value, ''$.conferralDate'') AS conferralDate
                        FROM OPENJSON(@BeforeJson, ''$.degrees'') AS existing
                        WHERE JSON_VALUE(existing.value, ''$.degreeType'') IN (''BSc'', ''MA'')
                        UNION ALL
                        SELECT degree_value.degreeType, degree_value.conferralDate
                        FROM
                        (
                            VALUES
                            (
                                CASE WHEN @LegacyDegreeCategory IN (''MD'', ''MD_PHD'')
                                     THEN ''MD'' END,
                                CASE WHEN @LegacyDegreeCategory IN (''MD'', ''MD_PHD'')
                                     THEN (SELECT TOP (1) JSON_VALUE(existing.value,
                                                   ''$.conferralDate'')
                                           FROM OPENJSON(@BeforeJson, ''$.degrees'') AS existing
                                           WHERE JSON_VALUE(existing.value,
                                                   ''$.degreeType'') = ''MD'') END
                            ),
                            (
                                CASE WHEN @LegacyDegreeCategory IN (''PHD'', ''MD_PHD'')
                                     THEN ''PhD'' END,
                                CASE WHEN @LegacyDegreeCategory IN (''PHD'', ''MD_PHD'')
                                     THEN JSON_VALUE(@DraftJson, ''$.phdDate'') END
                            )
                        ) AS degree_value(degreeType, conferralDate)
                        WHERE degree_value.degreeType IS NOT NULL
                    ) AS merged
                    FOR JSON PATH, INCLUDE_NULL_VALUES
                );
                SET @DraftJson = JSON_MODIFY(
                    @DraftJson, ''$.degrees'', JSON_QUERY(@MergedDegrees));
            END
            ELSE
                SET @DraftJson = JSON_MODIFY(
                    @DraftJson, ''$.degrees'',
                    JSON_QUERY(@BeforeJson, ''$.degrees''));
        END;

        -- A v16 publications write cannot contain the DOI list or direct
        -- Scholar flag. Preserve the list and derive the flag from v16 fields.
        IF @SectionCode = ''publications''
           AND JSON_QUERY(@BeforeJson, ''$.publications'') IS NOT NULL
           AND JSON_QUERY(@DraftJson, ''$.publications'') IS NULL
            SET @DraftJson = JSON_MODIFY(
                @DraftJson, ''$.publications'',
                JSON_QUERY(@BeforeJson, ''$.publications''));
        IF @SectionCode = ''publications''
           AND JSON_VALUE(@BeforeJson, ''$.hasGoogleScholarProfile'') IS NOT NULL
           AND JSON_VALUE(@DraftJson, ''$.hasGoogleScholarProfile'') IS NULL
            SET @DraftJson = JSON_MODIFY(
                @DraftJson, ''$.hasGoogleScholarProfile'',
                CASE
                  WHEN NULLIF(LTRIM(RTRIM(JSON_VALUE(@DraftJson,
                       ''$.googleScholarProfileUrl''))), N'''') IS NOT NULL
                    THEN CAST(1 AS bit)
                  WHEN JSON_VALUE(@DraftJson,
                       ''$.noGoogleScholarProfile'') = ''true'' THEN CAST(0 AS bit)
                  WHEN JSON_VALUE(@BeforeJson,
                       ''$.hasGoogleScholarProfile'') = ''true'' THEN CAST(1 AS bit)
                  ELSE CAST(0 AS bit)
                END);

        IF @ActualRowVersion IS NULL
            INSERT dbo.ApplicantSectionDraft
                (ApplicationId, SectionCode, DraftJson, SavedByIdentity)
            VALUES (@ApplicationId, @SectionCode, @DraftJson, N''APPLICANT'');
        ELSE
            UPDATE dbo.ApplicantSectionDraft
            SET DraftJson = @DraftJson,
                SavedByIdentity = N''APPLICANT'',
                SavedAtUtc = SYSUTCDATETIME()
            WHERE ApplicationId = @ApplicationId AND SectionCode = @SectionCode;
        INSERT dbo.ApplicantFieldCorrection
            (ApplicationId, SectionCode, FieldCode, PreviousValueJson, NewValueJson,
             CorrectedByIdentity, CorrectionSource)
        VALUES
            (@ApplicationId, @SectionCode, ''$'', @BeforeJson, @DraftJson,
             N''APPLICANT'', ''APPLICANT'');
        SELECT draft_row.ApplicantSectionDraftId, draft_row.ApplicationId,
               draft_row.SectionCode, draft_row.DraftJson, draft_row.RowVersion,
               open_scope.Reason, open_scope.ReopenedAtUtc
        FROM dbo.ApplicantSectionDraft AS draft_row
        OUTER APPLY
        (
            SELECT TOP (1) reopen_row.Reason, reopen_row.ReopenedAtUtc
            FROM dbo.ApplicantReopenScope AS reopen_row
            WHERE reopen_row.ApplicationId = draft_row.ApplicationId
              AND reopen_row.ScopeType = ''SECTION''
              AND reopen_row.ScopeCode = draft_row.SectionCode
              AND reopen_row.ClosedAtUtc IS NULL
            ORDER BY reopen_row.ReopenedAtUtc DESC,
                     reopen_row.ApplicantReopenScopeId DESC
        ) AS open_scope
        WHERE draft_row.ApplicationId = @ApplicationId
          AND draft_row.SectionCode = @SectionCode;
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.ReturnApplicantSubmissionForCorrection
    @ApplicantFinalConfirmationId uniqueidentifier,
    @SectionCode varchar(80),
    @Reason nvarchar(1000),
    @ReviewedByIdentity nvarchar(255),
    @ReviewerGroup varchar(40)
WITH EXECUTE AS ''EHFFinalConfirmationProcedureExecutor''
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @ReviewerGroup <> ''EHF-Administrators''
       OR NULLIF(LTRIM(RTRIM(@ReviewedByIdentity)), N'''') IS NULL
        THROW 52641, ''Administrator authorization is required.'', 1;
    IF @SectionCode NOT IN
       (''identity'', ''employment'', ''qualifications'', ''publications'', ''contribution'')
       OR NULLIF(LTRIM(RTRIM(@Reason)), N'''') IS NULL
        THROW 52643, ''A valid section and correction reason are required.'', 1;
    BEGIN TRANSACTION;
    BEGIN TRY
        DECLARE @ResolvedApplicationId uniqueidentifier;
        SELECT @ResolvedApplicationId = confirmation_row.ApplicationId
        FROM dbo.ApplicantFinalConfirmation AS confirmation_row WITH (UPDLOCK, HOLDLOCK)
        WHERE confirmation_row.ApplicantFinalConfirmationId = @ApplicantFinalConfirmationId
          AND confirmation_row.SupersededAtUtc IS NULL
          AND NOT EXISTS
              (SELECT 1 FROM dbo.ApplicantFinalReviewDecision AS existing
               WHERE existing.ApplicantFinalConfirmationId =
                     confirmation_row.ApplicantFinalConfirmationId);
        IF @ResolvedApplicationId IS NULL
            THROW 52642, ''The applicant submission is unavailable.'', 1;

        INSERT dbo.ApplicantFinalReviewDecision
            (ApplicantFinalConfirmationId, ReviewDecision,
             ReviewedByIdentity, ReviewerGroup)
        VALUES
            (@ApplicantFinalConfirmationId, ''REJECTED'',
             @ReviewedByIdentity, @ReviewerGroup);
        UPDATE dbo.ApplicantFinalConfirmation
        SET SupersededAtUtc = SYSUTCDATETIME()
        WHERE ApplicantFinalConfirmationId = @ApplicantFinalConfirmationId;
        INSERT dbo.ApplicantReopenScope
            (ApplicationId, ScopeType, ScopeCode, Reason, ReopenedByIdentity)
        VALUES
            (@ResolvedApplicationId, ''SECTION'', @SectionCode,
             LTRIM(RTRIM(@Reason)), @ReviewedByIdentity);
        UPDATE dbo.Application
        SET ApplicationStatus = ''IN_REVIEW'', ConfirmedAtUtc = NULL,
            UpdatedAtUtc = SYSUTCDATETIME()
        WHERE ApplicationId = @ResolvedApplicationId;
        INSERT dbo.AuditEvent
            (ApplicationId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
        VALUES
            (@ResolvedApplicationId, ''APPLICANT_CHANGES_RETURNED'', @ReviewedByIdentity,
             ''ApplicantFinalConfirmation'', @ApplicantFinalConfirmationId,
             (SELECT @ResolvedApplicationId AS applicationId,
                     ''IN_REVIEW'' AS status
              FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));

        SELECT decision_row.ApplicantFinalConfirmationId,
               @ResolvedApplicationId AS ApplicationId,
               decision_row.ReviewDecision,
               decision_row.ReviewedByIdentity,
               decision_row.ReviewedAtUtc
        FROM dbo.ApplicantFinalReviewDecision AS decision_row
        WHERE decision_row.ApplicantFinalConfirmationId = @ApplicantFinalConfirmationId;
        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;
END;
');

GRANT EXECUTE ON dbo.ReturnApplicantSubmissionForCorrection TO EHFApplicationRuntime;

EXEC(N'
CREATE PROCEDURE dbo.GetApplicantSectionDraftV17
    @SessionTokenSha256 binary(32),
    @SectionCode varchar(80)
AS
BEGIN
    SET NOCOUNT ON;
    SELECT draft_row.ApplicationId, draft_row.SectionCode,
           draft_row.DraftJson, draft_row.RowVersion,
           open_scope.Reason, open_scope.ReopenedAtUtc
    FROM dbo.ApplicantSession AS session_row
    JOIN dbo.ApplicantSectionDraft AS draft_row
      ON draft_row.ApplicationId = session_row.ApplicationId
    OUTER APPLY
    (
        SELECT TOP (1) reopen_row.Reason, reopen_row.ReopenedAtUtc
        FROM dbo.ApplicantReopenScope AS reopen_row
        WHERE reopen_row.ApplicationId = draft_row.ApplicationId
          AND reopen_row.ScopeType = ''SECTION''
          AND reopen_row.ScopeCode = draft_row.SectionCode
          AND reopen_row.ClosedAtUtc IS NULL
        ORDER BY reopen_row.ReopenedAtUtc DESC,
                 reopen_row.ApplicantReopenScopeId DESC
    ) AS open_scope
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME()
      AND draft_row.SectionCode = @SectionCode;
END;
');

GRANT EXECUTE ON dbo.GetApplicantSectionDraftV17 TO EHFApplicationRuntime;

EXEC(N'
ALTER PROCEDURE dbo.GetApplicantSectionConfirmation
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
      AND NOT EXISTS
      (
          SELECT 1
          FROM dbo.ApplicantReopenScope AS open_scope
          WHERE open_scope.ApplicationId = confirmation_row.ApplicationId
            AND open_scope.ScopeType = ''SECTION''
            AND open_scope.ScopeCode = confirmation_row.SectionCode
            AND open_scope.ClosedAtUtc IS NULL
            AND confirmation_row.ConfirmedAtUtc <= open_scope.ReopenedAtUtc
      )
    ORDER BY confirmation_row.ConfirmedAtUtc DESC;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.ConfirmApplicantSection
    @SessionTokenSha256 binary(32),
    @SectionCode varchar(80),
    @CanonicalSectionSha256 binary(32),
    @DraftRowVersion binary(8)
WITH EXECUTE AS ''EHFFinalConfirmationProcedureExecutor''
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @ApplicationId uniqueidentifier;
    SELECT @ApplicationId = session_row.ApplicationId
    FROM dbo.ApplicantSession AS session_row
    WHERE session_row.SessionTokenSha256 = @SessionTokenSha256
      AND session_row.RevokedAtUtc IS NULL
      AND session_row.IdleExpiresAtUtc > SYSUTCDATETIME()
      AND session_row.AbsoluteExpiresAtUtc > SYSUTCDATETIME();
    IF @ApplicationId IS NULL
        THROW 52128, ''The applicant session is unavailable.'', 1;
    IF @SectionCode NOT IN
       (''identity'', ''employment'', ''qualifications'', ''publications'', ''contribution'')
        THROW 52129, ''The applicant section is invalid.'', 1;

    DECLARE @StoredDraftJson nvarchar(max), @StoredDraftSavedAtUtc datetime2(7);
    SELECT @StoredDraftJson = draft_row.DraftJson,
           @StoredDraftSavedAtUtc = draft_row.SavedAtUtc
    FROM dbo.ApplicantSectionDraft AS draft_row
    WHERE draft_row.ApplicationId = @ApplicationId
      AND draft_row.SectionCode = @SectionCode
      AND draft_row.RowVersion = @DraftRowVersion;
    IF @StoredDraftJson IS NULL
        THROW 52130, ''The applicant section changed before confirmation.'', 1;
    IF EXISTS
    (
        SELECT 1
        FROM dbo.ApplicantReopenScope AS open_scope
        WHERE open_scope.ApplicationId = @ApplicationId
          AND open_scope.ScopeType = ''SECTION''
          AND open_scope.ScopeCode = @SectionCode
          AND open_scope.ClosedAtUtc IS NULL
          AND @StoredDraftSavedAtUtc <= open_scope.ReopenedAtUtc
    )
        THROW 52143, ''Save the returned section before confirming it again.'', 1;
    IF HASHBYTES(''SHA2_256'', CONVERT(varbinary(max), @StoredDraftJson)) <>
       @CanonicalSectionSha256
        THROW 52141, ''The applicant section hash is invalid.'', 1;
    IF EXISTS
    (
        SELECT 1
        FROM dbo.ApplicantReopenScope AS open_scope
        JOIN dbo.ApplicantSectionConfirmation AS prior_confirmation
          ON prior_confirmation.ApplicationId = open_scope.ApplicationId
         AND prior_confirmation.SectionCode = open_scope.ScopeCode
         AND prior_confirmation.ConfirmedAtUtc <= open_scope.ReopenedAtUtc
         AND prior_confirmation.CanonicalSectionSha256 = @CanonicalSectionSha256
        WHERE open_scope.ApplicationId = @ApplicationId
          AND open_scope.ScopeType = ''SECTION''
          AND open_scope.ScopeCode = @SectionCode
          AND open_scope.ClosedAtUtc IS NULL
    )
        THROW 52144, ''Make the requested correction before confirming this section.'', 1;

    IF NOT EXISTS
    (
        SELECT 1
        FROM dbo.ApplicantSectionConfirmation AS confirmation_row
        WHERE confirmation_row.ApplicationId = @ApplicationId
          AND confirmation_row.SectionCode = @SectionCode
          AND confirmation_row.CanonicalSectionSha256 = @CanonicalSectionSha256
          AND NOT EXISTS
          (
              SELECT 1
              FROM dbo.ApplicantReopenScope AS open_scope
              WHERE open_scope.ApplicationId = confirmation_row.ApplicationId
                AND open_scope.ScopeType = ''SECTION''
                AND open_scope.ScopeCode = confirmation_row.SectionCode
                AND open_scope.ClosedAtUtc IS NULL
                AND confirmation_row.ConfirmedAtUtc <= open_scope.ReopenedAtUtc
          )
    )
        INSERT dbo.ApplicantSectionConfirmation
            (ApplicationId, SectionCode, CanonicalSectionSha256,
             DraftRowVersion, ConfirmedByIdentity)
        VALUES
            (@ApplicationId, @SectionCode, @CanonicalSectionSha256,
             @DraftRowVersion, N''APPLICANT'');

    SELECT confirmation_row.ApplicantSectionConfirmationId,
           confirmation_row.SectionCode,
           confirmation_row.CanonicalSectionSha256,
           confirmation_row.DraftRowVersion,
           confirmation_row.ConfirmedAtUtc
    FROM dbo.ApplicantSectionConfirmation AS confirmation_row
    WHERE confirmation_row.ApplicationId = @ApplicationId
      AND confirmation_row.SectionCode = @SectionCode
      AND confirmation_row.CanonicalSectionSha256 = @CanonicalSectionSha256
    ORDER BY confirmation_row.ConfirmedAtUtc DESC;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_ApplicantFinalConfirmation_ReopenValidation
ON dbo.ApplicantFinalConfirmation
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS
    (
        SELECT 1
        FROM inserted AS final_row
        JOIN dbo.ApplicantReopenScope AS open_scope
          ON open_scope.ApplicationId = final_row.ApplicationId
         AND open_scope.ScopeType = ''SECTION''
         AND open_scope.ClosedAtUtc IS NULL
        LEFT JOIN dbo.ApplicantSectionDraft AS draft_row
          ON draft_row.ApplicationId = final_row.ApplicationId
         AND draft_row.SectionCode = open_scope.ScopeCode
        WHERE draft_row.ApplicantSectionDraftId IS NULL
           OR NOT (draft_row.SavedAtUtc > open_scope.ReopenedAtUtc)
           OR NOT EXISTS
              (
                  SELECT 1
                  FROM OPENJSON(final_row.ManifestJson, ''$.sections'')
                  WITH
                  (
                      SectionCode varchar(80) ''$.section'',
                      DraftVersion bigint ''$.rowVersion'',
                      CanonicalSha256 varchar(64) ''$.canonicalSha256''
                  ) AS manifest_section
                  JOIN dbo.ApplicantSectionConfirmation AS confirmation_row
                    ON confirmation_row.ApplicationId = final_row.ApplicationId
                   AND confirmation_row.SectionCode = manifest_section.SectionCode
                   AND CONVERT(bigint, confirmation_row.DraftRowVersion) =
                       manifest_section.DraftVersion
                   AND confirmation_row.CanonicalSectionSha256 =
                       CONVERT(binary(32), manifest_section.CanonicalSha256, 2)
                  WHERE manifest_section.SectionCode = open_scope.ScopeCode
                    AND confirmation_row.ConfirmedAtUtc > open_scope.ReopenedAtUtc
                    AND NOT EXISTS
                    (
                        SELECT 1
                        FROM dbo.ApplicantSectionConfirmation AS prior_confirmation
                        WHERE prior_confirmation.ApplicationId = final_row.ApplicationId
                          AND prior_confirmation.SectionCode = open_scope.ScopeCode
                          AND prior_confirmation.ConfirmedAtUtc <= open_scope.ReopenedAtUtc
                          AND prior_confirmation.CanonicalSectionSha256 =
                              confirmation_row.CanonicalSectionSha256
                    )
              )
    )
        THROW 52136, ''A returned applicant section must be saved and reconfirmed.'', 1;

    UPDATE open_scope
    SET ClosedAtUtc = SYSUTCDATETIME()
    FROM dbo.ApplicantReopenScope AS open_scope
    JOIN inserted AS final_row
      ON final_row.ApplicationId = open_scope.ApplicationId
    WHERE open_scope.ClosedAtUtc IS NULL;
END;
');

EXEC(N'
ALTER PROCEDURE dbo.PromoteApprovedApplicantDrafts
    @ApplicationId uniqueidentifier,
    @ApprovedByIdentity nvarchar(255)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @Projection nvarchar(max), @Identity nvarchar(max),
            @Employment nvarchar(max), @Qualifications nvarchar(max),
            @Publications nvarchar(max), @Contribution nvarchar(max),
            @Degrees nvarchar(max), @UsesLegacyDegrees bit = 0,
            @PostdocRaw nvarchar(200);
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
    SET @Degrees = JSON_QUERY(@Qualifications, ''$.degrees'');
    IF @Degrees IS NULL
    BEGIN
        SET @UsesLegacyDegrees = 1;
        SET @Degrees =
        (
            SELECT degree_value.degreeType, degree_value.conferralDate
            FROM
            (
                VALUES
                (
                    CASE JSON_VALUE(@Qualifications, ''$.degreeCategory'')
                      WHEN ''MD'' THEN ''MD'' WHEN ''PHD'' THEN ''PhD''
                      WHEN ''MD_PHD'' THEN ''MD'' END,
                    CASE WHEN JSON_VALUE(@Qualifications,
                              ''$.degreeCategory'') = ''PHD''
                         THEN TRY_CONVERT(date, JSON_VALUE(
                              @Qualifications, ''$.phdDate'')) END
                ),
                (
                    CASE WHEN JSON_VALUE(@Qualifications,
                              ''$.degreeCategory'') = ''MD_PHD''
                         THEN ''PhD'' END,
                    CASE WHEN JSON_VALUE(@Qualifications,
                              ''$.degreeCategory'') = ''MD_PHD''
                         THEN TRY_CONVERT(date, JSON_VALUE(
                              @Qualifications, ''$.phdDate'')) END
                )
            ) AS degree_value(degreeType, conferralDate)
            WHERE degree_value.degreeType IS NOT NULL
            FOR JSON PATH, INCLUDE_NULL_VALUES
        );
    END;
    IF NOT EXISTS (SELECT 1 FROM OPENJSON(@Degrees))
       OR EXISTS
          (SELECT 1 FROM OPENJSON(@Degrees)
           WITH (degreeType nvarchar(20) ''$.degreeType'',
                 conferralDate date ''$.conferralDate'') AS degree_row
           WHERE degree_row.degreeType NOT IN (''BSc'', ''MA'', ''MD'', ''PhD'')
              OR (@UsesLegacyDegrees = 0 AND degree_row.conferralDate IS NULL)
              OR (degree_row.degreeType = ''PhD'' AND degree_row.conferralDate IS NULL))
        THROW 52645, ''The approved qualification list is invalid.'', 1;

    SET @PostdocRaw = LOWER(NULLIF(LTRIM(RTRIM(JSON_VALUE(
        @Employment, ''$.postdoctoralEmploymentStatus''))), N''''));
    IF @PostdocRaw IS NULL OR @PostdocRaw NOT IN
       (N''true'', N''yes'', N''employed'', N''current'', N''currently employed'',
        N''false'', N''no'', N''not employed'', N''unemployed'', N''none'',
        N''future'', N''future appointment'', N''not yet'', N''pending'')
        THROW 52646, ''The approved postdoctoral employment status requires review.'', 1;

    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.fullName'', JSON_VALUE(@Identity, ''$.fullName''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.preferredName'', JSON_VALUE(@Identity, ''$.preferredName''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.registeredEmail'', JSON_VALUE(@Identity, ''$.registeredEmail''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.alternativeEmail'', JSON_VALUE(@Identity, ''$.alternativeEmail''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.telephone'', JSON_VALUE(@Identity, ''$.telephone''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.birthMonth'', TRY_CONVERT(int, JSON_VALUE(@Identity, ''$.birthMonth'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.birthYear'', TRY_CONVERT(int, JSON_VALUE(@Identity, ''$.birthYear'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.gender'', JSON_VALUE(@Identity, ''$.gender''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.genderSelfDescription'', NULL);
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.institute'', JSON_VALUE(@Employment, ''$.institute''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.principalInvestigator'', JSON_VALUE(@Employment, ''$.principalInvestigator''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.positionTitle'', JSON_VALUE(@Employment, ''$.positionTitle''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.postdoctoralEmploymentStatus'',
        CASE LOWER(JSON_VALUE(@Employment, ''$.postdoctoralEmploymentStatus''))
          WHEN ''true'' THEN CAST(1 AS bit)
          WHEN ''yes'' THEN CAST(1 AS bit)
          WHEN ''employed'' THEN CAST(1 AS bit)
          WHEN ''current'' THEN CAST(1 AS bit)
          WHEN ''currently employed'' THEN CAST(1 AS bit)
          WHEN ''false'' THEN CAST(0 AS bit)
          WHEN ''no'' THEN CAST(0 AS bit)
          WHEN ''not employed'' THEN CAST(0 AS bit)
          WHEN ''unemployed'' THEN CAST(0 AS bit)
          WHEN ''none'' THEN CAST(0 AS bit)
          WHEN ''future'' THEN CAST(0 AS bit)
          WHEN ''future appointment'' THEN CAST(0 AS bit)
          WHEN ''not yet'' THEN CAST(0 AS bit)
          WHEN ''pending'' THEN CAST(0 AS bit)
        END);
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.employmentStartDate'', JSON_VALUE(@Employment, ''$.employmentStartDate''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.employmentEndDate'', JSON_VALUE(@Employment, ''$.employmentEndDate''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.futureStartDate'', JSON_VALUE(@Employment, ''$.futureStartDate''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.researchArea'', JSON_VALUE(@Employment, ''$.researchArea''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.clinicalWorkPercent'', TRY_CONVERT(decimal(5,2), JSON_VALUE(@Employment, ''$.clinicalWorkPercent'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.firstAuthorDeclaration'',
        CASE JSON_VALUE(@Employment, ''$.firstAuthorDeclaration'')
             WHEN ''true'' THEN CAST(1 AS bit) WHEN ''false'' THEN CAST(0 AS bit) END);
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.degrees'', JSON_QUERY(@Degrees));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.degreeCategory'', NULL);
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.phdDate'', NULL);
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.firstAuthorPaperCount'', TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.firstAuthorPaperCount'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.lastAuthorPaperCount'', TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.lastAuthorPaperCount'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.totalPaperCount'', TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.totalPaperCount'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.hIndex'', TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.hIndex'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.applicantReportedCitationTotal'', TRY_CONVERT(bigint, JSON_VALUE(@Publications, ''$.applicantReportedCitationTotal'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.orcid'', JSON_VALUE(@Publications, ''$.orcid''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.googleScholarProfileUrl'', JSON_VALUE(@Publications, ''$.googleScholarProfileUrl''));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.hasGoogleScholarProfile'',
        CASE
          WHEN JSON_VALUE(@Publications, ''$.hasGoogleScholarProfile'') = ''true'' THEN CAST(1 AS bit)
          WHEN JSON_VALUE(@Publications, ''$.hasGoogleScholarProfile'') = ''false'' THEN CAST(0 AS bit)
          WHEN NULLIF(LTRIM(RTRIM(JSON_VALUE(@Publications,
               ''$.googleScholarProfileUrl''))), N'''') IS NOT NULL THEN CAST(1 AS bit)
          WHEN JSON_VALUE(@Publications, ''$.noGoogleScholarProfile'') = ''true'' THEN CAST(0 AS bit)
        END);
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.publications'',
        JSON_QUERY(COALESCE(JSON_QUERY(@Publications, ''$.publications''), N''[]'')));
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.noGoogleScholarProfile'', NULL);
    SET @Projection = JSON_MODIFY(@Projection, ''$.applicant.googleScholarCitationTotal'', NULL);
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
    INSERT dbo.Qualification
        (ApplicationId, DegreeType, PhdDate, ConferralDate)
    SELECT @ApplicationId,
           CASE degree_row.degreeType
             WHEN ''BSc'' THEN ''BSC'' WHEN ''MA'' THEN ''MA''
             WHEN ''MD'' THEN ''MD'' WHEN ''PhD'' THEN ''PHD'' END,
           CASE WHEN degree_row.degreeType = ''PhD''
                THEN degree_row.conferralDate END,
           degree_row.conferralDate
    FROM OPENJSON(@Degrees)
    WITH (degreeType nvarchar(20) ''$.degreeType'',
          conferralDate date ''$.conferralDate'') AS degree_row;
    MERGE dbo.Bibliometrics AS target
    USING (SELECT @ApplicationId AS ApplicationId) AS source
       ON target.ApplicationId = source.ApplicationId
    WHEN MATCHED THEN UPDATE SET
       FirstAuthorPaperCount = TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.firstAuthorPaperCount'')),
       LastAuthorPaperCount = TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.lastAuthorPaperCount'')),
       TotalPaperCount = TRY_CONVERT(int, JSON_VALUE(@Publications, ''$.totalPaperCount'')),
       UpdatedAtUtc = SYSUTCDATETIME()
    WHEN NOT MATCHED THEN INSERT
       (ApplicationId, FirstAuthorPaperCount, LastAuthorPaperCount, TotalPaperCount)
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
        COALESCE(
            (SELECT STRING_AGG(JSON_VALUE(degree_row.value, ''$.degreeType''), N'', '')
             WITHIN GROUP (ORDER BY TRY_CONVERT(int, degree_row.[key]))
             FROM OPENJSON(qualification_section.SnapshotJson, ''$.degrees'') AS degree_row),
            JSON_VALUE(qualification_section.SnapshotJson, ''$.degreeCategory''),
            JSON_VALUE(legacy_section.SnapshotJson, ''$.degree'')) AS Degree,
        TRY_CONVERT(decimal(8,2), JSON_VALUE(legacy_section.SnapshotJson, ''$.age_observation''))
            AS AgeObservation,
        COALESCE(
            TRY_CONVERT(
                decimal(8,2),
                DATEDIFF(
                    day,
                    academic_degree.PhdConferralDate,
                    TRY_CONVERT(date, call_row.ApplicationDeadlineUtc)
                ) / 365.2425
            ),
            TRY_CONVERT(decimal(8,2), JSON_VALUE(
                legacy_section.SnapshotJson, ''$.academic_age_observation''))
        ) AS AcademicAgeObservation,
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
    (
        SELECT COALESCE(
            (SELECT MIN(TRY_CONVERT(date, JSON_VALUE(
                        degree_row.value, ''$.conferralDate'')))
             FROM OPENJSON(
                    qualification_section.SnapshotJson, ''$.degrees'') AS degree_row
             WHERE JSON_VALUE(
                       degree_row.value, ''$.degreeType'') = ''PhD''),
            CASE
              WHEN JSON_VALUE(qualification_section.SnapshotJson,
                              ''$.degreeCategory'') IN (''PHD'', ''MD_PHD'')
                THEN TRY_CONVERT(date, JSON_VALUE(
                     qualification_section.SnapshotJson, ''$.phdDate''))
            END,
            (SELECT MIN(COALESCE(qualification.ConferralDate,
                                 qualification.PhdDate))
             FROM dbo.Qualification AS qualification
             WHERE qualification.ApplicationId = application_row.ApplicationId
               AND qualification.DegreeType IN (''PHD'', ''MD_PHD''))
        ) AS PhdConferralDate
    ) AS academic_degree
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
