SET NOCOUNT ON;
SET XACT_ABORT OFF;

DECLARE @RequiredTable TABLE (TableName sysname NOT NULL PRIMARY KEY);
INSERT @RequiredTable (TableName)
VALUES
    (N'FellowshipCall'),
    (N'Applicant'),
    (N'ApplicantContact'),
    (N'Application'),
    (N'EmploymentAffiliation'),
    (N'Qualification'),
    (N'EligibilityDeclaration'),
    (N'Bibliometrics'),
    (N'ContributionStatement'),
    (N'FieldProvenance'),
    (N'ApplicationSectionVersion');

IF EXISTS
(
    SELECT 1
    FROM @RequiredTable AS required_table
    WHERE OBJECT_ID(N'dbo.' + required_table.TableName, N'U') IS NULL
)
    THROW 51200, 'A required application-core table is missing.', 1;

IF OBJECT_ID(N'dbo.ApplicationDerivedAge', N'V') IS NULL
    THROW 51201, 'The deterministic age view is missing.', 1;

IF EXISTS
(
    SELECT 1
    FROM sys.columns
    WHERE name LIKE '%Birth%Day%'
)
    THROW 51202, 'Birth day data must not exist anywhere in the schema.', 1;

IF NOT EXISTS
(
    SELECT 1
    FROM sys.columns AS column_row
    JOIN sys.types AS type_row ON type_row.user_type_id = column_row.user_type_id
    WHERE column_row.object_id = OBJECT_ID(N'dbo.Qualification')
      AND column_row.name = N'PhdDate'
      AND type_row.name = N'date'
)
    THROW 51203, 'Qualification.PhdDate must be an exact DATE.', 1;

IF EXISTS
(
    SELECT 1
    FROM sys.foreign_keys
    WHERE parent_object_id IN
    (
        SELECT OBJECT_ID(N'dbo.' + TableName) FROM @RequiredTable
    )
      AND (is_disabled = 1 OR is_not_trusted = 1)
)
    THROW 51204, 'Application-core foreign keys must be enabled and trusted.', 1;

DECLARE @MutableTable TABLE (TableName sysname NOT NULL PRIMARY KEY);
INSERT @MutableTable (TableName)
VALUES
    (N'FellowshipCall'),
    (N'Applicant'),
    (N'ApplicantContact'),
    (N'Application'),
    (N'EmploymentAffiliation'),
    (N'Qualification'),
    (N'EligibilityDeclaration'),
    (N'Bibliometrics'),
    (N'ContributionStatement');

IF EXISTS
(
    SELECT 1
    FROM @MutableTable AS mutable_table
    WHERE NOT EXISTS
    (
        SELECT 1
        FROM sys.columns AS column_row
        JOIN sys.types AS type_row ON type_row.user_type_id = column_row.user_type_id
        WHERE column_row.object_id = OBJECT_ID(N'dbo.' + mutable_table.TableName)
          AND column_row.name = N'RowVersion'
          AND type_row.name IN (N'timestamp', N'rowversion')
    )
)
    THROW 51205, 'Every mutable application table must have rowversion.', 1;

IF OBJECT_ID(N'dbo.TR_FieldProvenance_AppendOnly', N'TR') IS NULL
   OR OBJECT_ID(N'dbo.TR_ApplicationSectionVersion_AppendOnly', N'TR') IS NULL
    THROW 51206, 'Immutable application-history guards are missing.', 1;

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @FellowshipCallId uniqueidentifier = NEWID();
    DECLARE @ApplicantId uniqueidentifier = NEWID();
    DECLARE @ApplicationId uniqueidentifier = NEWID();
    DECLARE @MissingApplicantId uniqueidentifier = NEWID();
    DECLARE @MissingApplicationId uniqueidentifier = NEWID();

    INSERT dbo.FellowshipCall
        (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
    VALUES
        (@FellowshipCallId, N'VALIDATOR-2026', N'Validator call', 'DRAFT',
         CONVERT(datetime2(7), '2026-08-31T23:59:59'));

    INSERT dbo.Applicant
        (ApplicantId, LegalGivenNames, LegalFamilyName, BirthYear, BirthMonth)
    VALUES
        (@ApplicantId, N'Synthetic', N'Complete', 1990, 2),
        (@MissingApplicantId, N'Synthetic', N'Missing', NULL, NULL);

    INSERT dbo.Application
        (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus)
    VALUES
        (@ApplicationId, @FellowshipCallId, @ApplicantId, 'DRAFT'),
        (@MissingApplicationId, @FellowshipCallId, @MissingApplicantId, 'DRAFT');

    INSERT dbo.Qualification
        (ApplicationId, DegreeType, AwardingInstitution, PhdDate)
    VALUES
        (@ApplicationId, 'PHD', N'Synthetic institution', CONVERT(date, '2025-08-31'));

    INSERT dbo.Bibliometrics (ApplicationId)
    VALUES (@MissingApplicationId);

    IF EXISTS
    (
        SELECT 1
        FROM dbo.Bibliometrics
        WHERE ApplicationId = @MissingApplicationId
          AND
          (
              FirstAuthorPaperCount IS NOT NULL
              OR LastAuthorPaperCount IS NOT NULL
              OR TotalPaperCount IS NOT NULL
              OR GoogleScholarCitationCount IS NOT NULL
          )
    )
        THROW 51207, 'Missing numeric values must remain NULL.', 1;

    IF NOT EXISTS
    (
        SELECT 1
        FROM dbo.ApplicationDerivedAge
        WHERE ApplicationId = @ApplicationId
          AND AnagraphicAgeMonths = 438
          AND ABS(AnagraphicAgeYears - CONVERT(decimal(18,6), 36.500000)) < 0.000001
          AND AcademicAgeDays = 365
          AND ABS(AcademicAgeYears - CONVERT(decimal(18,6), 0.999336)) < 0.000001
    )
        THROW 51208, 'Derived ages do not follow the deterministic contract.', 1;

    IF NOT EXISTS
    (
        SELECT 1
        FROM dbo.ApplicationDerivedAge
        WHERE ApplicationId = @MissingApplicationId
          AND AnagraphicAgeMonths IS NULL
          AND AnagraphicAgeYears IS NULL
          AND AcademicAgeDays IS NULL
          AND AcademicAgeYears IS NULL
    )
        THROW 51209, 'Derived ages must be NULL when required inputs are missing.', 1;

    INSERT dbo.ContributionStatement (ApplicationId, StatementText)
    VALUES (@ApplicationId, REPLICATE(N' ', 1000));

    BEGIN TRY
        INSERT dbo.ContributionStatement (ApplicationId, StatementText)
        VALUES (@MissingApplicationId, REPLICATE(N' ', 1001));
        THROW 51210, 'A 1,001-character contribution statement was accepted.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() = 51210 THROW;
        IF ERROR_NUMBER() <> 547 THROW;
    END CATCH;

    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 002 application core';
