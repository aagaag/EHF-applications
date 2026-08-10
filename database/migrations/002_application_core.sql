SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE TABLE dbo.FellowshipCall
(
    FellowshipCallId uniqueidentifier NOT NULL
        CONSTRAINT DF_FellowshipCall_Id DEFAULT NEWSEQUENTIALID(),
    CallCode nvarchar(50) NOT NULL,
    DisplayName nvarchar(200) NOT NULL,
    CallStatus varchar(20) NOT NULL,
    OpensAtUtc datetime2(7) NULL,
    ApplicationDeadlineUtc datetime2(7) NOT NULL,
    ApplicantReviewDeadlineUtc datetime2(7) NULL,
    SettingsJson nvarchar(max) NOT NULL
        CONSTRAINT DF_FellowshipCall_SettingsJson DEFAULT N'{}',
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_FellowshipCall_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    UpdatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_FellowshipCall_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_FellowshipCall PRIMARY KEY (FellowshipCallId),
    CONSTRAINT UQ_FellowshipCall_CallCode UNIQUE (CallCode),
    CONSTRAINT CK_FellowshipCall_CallCode CHECK (LEN(CallCode) > 0),
    CONSTRAINT CK_FellowshipCall_DisplayName CHECK (LEN(DisplayName) > 0),
    CONSTRAINT CK_FellowshipCall_Status CHECK
        (CallStatus IN ('DRAFT', 'OPEN', 'CLOSED', 'ARCHIVED')),
    CONSTRAINT CK_FellowshipCall_SettingsJson CHECK (ISJSON(SettingsJson) = 1),
    CONSTRAINT CK_FellowshipCall_Deadlines CHECK
        (ApplicantReviewDeadlineUtc IS NULL
         OR ApplicantReviewDeadlineUtc >= ApplicationDeadlineUtc)
);

CREATE TABLE dbo.Applicant
(
    ApplicantId uniqueidentifier NOT NULL
        CONSTRAINT DF_Applicant_Id DEFAULT NEWSEQUENTIALID(),
    LegalGivenNames nvarchar(200) NOT NULL,
    LegalFamilyName nvarchar(200) NOT NULL,
    PreferredName nvarchar(200) NULL,
    BirthYear smallint NULL,
    BirthMonth tinyint NULL,
    SelfReportedGender nvarchar(100) NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_Applicant_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    UpdatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_Applicant_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_Applicant PRIMARY KEY (ApplicantId),
    CONSTRAINT CK_Applicant_GivenNames CHECK (LEN(LegalGivenNames) > 0),
    CONSTRAINT CK_Applicant_FamilyName CHECK (LEN(LegalFamilyName) > 0),
    CONSTRAINT CK_Applicant_BirthMonthYear CHECK
    (
        (BirthYear IS NULL AND BirthMonth IS NULL)
        OR (BirthYear BETWEEN 1900 AND 2200 AND BirthMonth BETWEEN 1 AND 12)
    )
);

CREATE TABLE dbo.ApplicantContact
(
    ApplicantContactId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantContact_Id DEFAULT NEWSEQUENTIALID(),
    ApplicantId uniqueidentifier NOT NULL,
    ContactType varchar(30) NOT NULL,
    ContactValue nvarchar(320) NOT NULL,
    IsPrimary bit NOT NULL CONSTRAINT DF_ApplicantContact_IsPrimary DEFAULT 0,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantContact_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    UpdatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantContact_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicantContact PRIMARY KEY (ApplicantContactId),
    CONSTRAINT FK_ApplicantContact_Applicant FOREIGN KEY (ApplicantId)
        REFERENCES dbo.Applicant (ApplicantId),
    CONSTRAINT UQ_ApplicantContact_Value UNIQUE
        (ApplicantId, ContactType, ContactValue),
    CONSTRAINT CK_ApplicantContact_Type CHECK
        (ContactType IN ('REGISTERED_EMAIL', 'ALTERNATIVE_EMAIL', 'TELEPHONE')),
    CONSTRAINT CK_ApplicantContact_Value CHECK (LEN(ContactValue) > 0)
);

CREATE UNIQUE INDEX UX_ApplicantContact_PrimaryType
ON dbo.ApplicantContact (ApplicantId, ContactType)
WHERE IsPrimary = 1;

CREATE TABLE dbo.Application
(
    ApplicationId uniqueidentifier NOT NULL
        CONSTRAINT DF_Application_Id DEFAULT NEWSEQUENTIALID(),
    FellowshipCallId uniqueidentifier NOT NULL,
    ApplicantId uniqueidentifier NOT NULL,
    ApplicationStatus varchar(20) NOT NULL,
    SubmittedAtUtc datetime2(7) NULL,
    ConfirmedAtUtc datetime2(7) NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_Application_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    UpdatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_Application_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_Application PRIMARY KEY (ApplicationId),
    CONSTRAINT FK_Application_FellowshipCall FOREIGN KEY (FellowshipCallId)
        REFERENCES dbo.FellowshipCall (FellowshipCallId),
    CONSTRAINT FK_Application_Applicant FOREIGN KEY (ApplicantId)
        REFERENCES dbo.Applicant (ApplicantId),
    CONSTRAINT UQ_Application_CallApplicant UNIQUE (FellowshipCallId, ApplicantId),
    CONSTRAINT CK_Application_Status CHECK
        (ApplicationStatus IN
            ('DRAFT', 'IMPORTED', 'INVITED', 'IN_REVIEW', 'CONFIRMED', 'WITHDRAWN')),
    CONSTRAINT CK_Application_Confirmation CHECK
        (ConfirmedAtUtc IS NULL OR ApplicationStatus = 'CONFIRMED')
);

CREATE TABLE dbo.EmploymentAffiliation
(
    EmploymentAffiliationId uniqueidentifier NOT NULL
        CONSTRAINT DF_EmploymentAffiliation_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    InstitutionName nvarchar(300) NOT NULL,
    DepartmentName nvarchar(300) NULL,
    PositionTitle nvarchar(200) NULL,
    EmploymentPercent decimal(5,2) NULL,
    ClinicalWorkPercent decimal(5,2) NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_EmploymentAffiliation_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    UpdatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_EmploymentAffiliation_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_EmploymentAffiliation PRIMARY KEY (EmploymentAffiliationId),
    CONSTRAINT FK_EmploymentAffiliation_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT UQ_EmploymentAffiliation_ApplicationInstitution UNIQUE
        (ApplicationId, InstitutionName),
    CONSTRAINT CK_EmploymentAffiliation_Institution CHECK (LEN(InstitutionName) > 0),
    CONSTRAINT CK_EmploymentAffiliation_EmploymentPercent CHECK
        (EmploymentPercent IS NULL OR EmploymentPercent BETWEEN 0.01 AND 100.00),
    CONSTRAINT CK_EmploymentAffiliation_ClinicalPercent CHECK
        (ClinicalWorkPercent IS NULL OR ClinicalWorkPercent BETWEEN 0.01 AND 100.00)
);

CREATE TABLE dbo.Qualification
(
    QualificationId uniqueidentifier NOT NULL
        CONSTRAINT DF_Qualification_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    DegreeType varchar(20) NOT NULL,
    AwardingInstitution nvarchar(300) NULL,
    PhdDate date NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_Qualification_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    UpdatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_Qualification_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_Qualification PRIMARY KEY (QualificationId),
    CONSTRAINT FK_Qualification_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT CK_Qualification_DegreeType CHECK
        (DegreeType IN ('MD', 'PHD', 'MD_PHD', 'OTHER')),
    CONSTRAINT CK_Qualification_PhdDate CHECK
        ((DegreeType IN ('PHD', 'MD_PHD') AND PhdDate IS NOT NULL)
         OR (DegreeType NOT IN ('PHD', 'MD_PHD') AND PhdDate IS NULL))
);

CREATE TABLE dbo.EligibilityDeclaration
(
    EligibilityDeclarationId uniqueidentifier NOT NULL
        CONSTRAINT DF_EligibilityDeclaration_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    DeclarationCode varchar(80) NOT NULL,
    DeclaredValue bit NULL,
    Explanation nvarchar(2000) NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_EligibilityDeclaration_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    UpdatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_EligibilityDeclaration_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_EligibilityDeclaration PRIMARY KEY (EligibilityDeclarationId),
    CONSTRAINT FK_EligibilityDeclaration_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT UQ_EligibilityDeclaration_Code UNIQUE (ApplicationId, DeclarationCode),
    CONSTRAINT CK_EligibilityDeclaration_Code CHECK (LEN(DeclarationCode) > 0)
);

CREATE TABLE dbo.Bibliometrics
(
    BibliometricsId uniqueidentifier NOT NULL
        CONSTRAINT DF_Bibliometrics_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    FirstAuthorPaperCount int NULL,
    LastAuthorPaperCount int NULL,
    TotalPaperCount int NULL,
    GoogleScholarCitationCount bigint NULL,
    GoogleScholarVerifiedAtUtc datetime2(7) NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_Bibliometrics_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    UpdatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_Bibliometrics_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_Bibliometrics PRIMARY KEY (BibliometricsId),
    CONSTRAINT FK_Bibliometrics_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT UQ_Bibliometrics_Application UNIQUE (ApplicationId),
    CONSTRAINT CK_Bibliometrics_FirstAuthor CHECK
        (FirstAuthorPaperCount IS NULL OR FirstAuthorPaperCount >= 0),
    CONSTRAINT CK_Bibliometrics_LastAuthor CHECK
        (LastAuthorPaperCount IS NULL OR LastAuthorPaperCount >= 0),
    CONSTRAINT CK_Bibliometrics_Total CHECK
        (TotalPaperCount IS NULL OR TotalPaperCount >= 0),
    CONSTRAINT CK_Bibliometrics_Citations CHECK
        (GoogleScholarCitationCount IS NULL OR GoogleScholarCitationCount >= 0)
);

CREATE TABLE dbo.ContributionStatement
(
    ContributionStatementId uniqueidentifier NOT NULL
        CONSTRAINT DF_ContributionStatement_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    StatementText nvarchar(max) COLLATE Latin1_General_100_CI_AS_SC NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ContributionStatement_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    UpdatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ContributionStatement_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ContributionStatement PRIMARY KEY (ContributionStatementId),
    CONSTRAINT FK_ContributionStatement_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT UQ_ContributionStatement_Application UNIQUE (ApplicationId),
    CONSTRAINT CK_ContributionStatement_Length CHECK
        (LEN(StatementText + NCHAR(1)) - 1 BETWEEN 1 AND 1000)
);

-- The _SC collation counts supplementary Unicode characters as one code point.
-- App input validation repeats the <= 1,000 Unicode-code-point rule before SQL.
-- Appending NCHAR(1) makes LEN count trailing spaces instead of discarding them.

CREATE TABLE dbo.FieldProvenance
(
    FieldProvenanceId uniqueidentifier NOT NULL
        CONSTRAINT DF_FieldProvenance_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    EntityType varchar(80) NOT NULL,
    EntityId uniqueidentifier NOT NULL,
    FieldName varchar(128) NOT NULL,
    VersionNumber int NOT NULL,
    SourceType varchar(40) NOT NULL,
    SourceIdentifier nvarchar(500) NOT NULL,
    ValueSha256 binary(32) NULL,
    SourceObservedAtUtc datetime2(7) NULL,
    RecordedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_FieldProvenance_RecordedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_FieldProvenance PRIMARY KEY (FieldProvenanceId),
    CONSTRAINT FK_FieldProvenance_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT UQ_FieldProvenance_Version UNIQUE
        (ApplicationId, EntityType, EntityId, FieldName, VersionNumber),
    CONSTRAINT CK_FieldProvenance_EntityType CHECK (LEN(EntityType) > 0),
    CONSTRAINT CK_FieldProvenance_FieldName CHECK (LEN(FieldName) > 0),
    CONSTRAINT CK_FieldProvenance_Version CHECK (VersionNumber > 0),
    CONSTRAINT CK_FieldProvenance_SourceType CHECK
        (SourceType IN
            ('REGISTER', 'PROVIDED_DOCUMENT', 'APPLICANT', 'ADMINISTRATOR', 'SYSTEM')),
    CONSTRAINT CK_FieldProvenance_SourceIdentifier CHECK (LEN(SourceIdentifier) > 0)
);

CREATE TABLE dbo.ApplicationSectionVersion
(
    ApplicationSectionVersionId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicationSectionVersion_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    SectionCode varchar(80) NOT NULL,
    VersionNumber int NOT NULL,
    SnapshotJson nvarchar(max) NOT NULL,
    ChangedByIdentity nvarchar(255) NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicationSectionVersion_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicationSectionVersion PRIMARY KEY (ApplicationSectionVersionId),
    CONSTRAINT FK_ApplicationSectionVersion_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT UQ_ApplicationSectionVersion UNIQUE
        (ApplicationId, SectionCode, VersionNumber),
    CONSTRAINT CK_ApplicationSectionVersion_Code CHECK (LEN(SectionCode) > 0),
    CONSTRAINT CK_ApplicationSectionVersion_Number CHECK (VersionNumber > 0),
    CONSTRAINT CK_ApplicationSectionVersion_Snapshot CHECK (ISJSON(SnapshotJson) = 1),
    CONSTRAINT CK_ApplicationSectionVersion_Actor CHECK (LEN(ChangedByIdentity) > 0)
);

EXEC(N'
CREATE VIEW dbo.ApplicationDerivedAge
AS
    SELECT
        application_row.ApplicationId,
        CASE
            WHEN applicant.BirthYear IS NULL OR applicant.BirthMonth IS NULL THEN NULL
            ELSE DATEDIFF
            (
                month,
                DATEFROMPARTS(applicant.BirthYear, applicant.BirthMonth, 1),
                DATEFROMPARTS
                (
                    YEAR(call_row.ApplicationDeadlineUtc),
                    MONTH(call_row.ApplicationDeadlineUtc),
                    1
                )
            )
        END AS AnagraphicAgeMonths,
        CASE
            WHEN applicant.BirthYear IS NULL OR applicant.BirthMonth IS NULL THEN NULL
            ELSE CONVERT(decimal(18,6), DATEDIFF
            (
                month,
                DATEFROMPARTS(applicant.BirthYear, applicant.BirthMonth, 1),
                DATEFROMPARTS
                (
                    YEAR(call_row.ApplicationDeadlineUtc),
                    MONTH(call_row.ApplicationDeadlineUtc),
                    1
                )
            )) / CONVERT(decimal(18,6), 12.0)
        END AS AnagraphicAgeYears,
        CASE
            WHEN phd.PhdDate IS NULL THEN NULL
            ELSE DATEDIFF(day, phd.PhdDate, CONVERT(date, call_row.ApplicationDeadlineUtc))
        END AS AcademicAgeDays,
        CASE
            WHEN phd.PhdDate IS NULL THEN NULL
            ELSE CONVERT(decimal(18,6), DATEDIFF
            (
                day,
                phd.PhdDate,
                CONVERT(date, call_row.ApplicationDeadlineUtc)
            )) / CONVERT(decimal(18,6), 365.2425)
        END AS AcademicAgeYears
    FROM dbo.Application AS application_row
    JOIN dbo.Applicant AS applicant
        ON applicant.ApplicantId = application_row.ApplicantId
    JOIN dbo.FellowshipCall AS call_row
        ON call_row.FellowshipCallId = application_row.FellowshipCallId
    OUTER APPLY
    (
        SELECT MAX(qualification.PhdDate) AS PhdDate
        FROM dbo.Qualification AS qualification
        WHERE qualification.ApplicationId = application_row.ApplicationId
          AND qualification.DegreeType IN (''PHD'', ''MD_PHD'')
    ) AS phd;
');

EXEC(N'
CREATE TRIGGER dbo.TR_FieldProvenance_AppendOnly
ON dbo.FieldProvenance
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 51021, ''Field provenance is append-only.'', 1;
END;
');

EXEC(N'
CREATE TRIGGER dbo.TR_ApplicationSectionVersion_AppendOnly
ON dbo.ApplicationSectionVersion
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 51022, ''Application section versions are append-only.'', 1;
END;
');
