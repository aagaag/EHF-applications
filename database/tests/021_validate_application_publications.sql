SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.ApplicationPublication', N'U') IS NULL
    THROW 54030, 'Application publications are missing.', 1;
IF OBJECT_ID(N'dbo.ApplicationPublicationSourceOccurrence', N'U') IS NULL
    THROW 54031, 'Application publication source occurrences are missing.', 1;
IF OBJECT_ID(N'dbo.PublicationMetadataObservation', N'U') IS NULL
    THROW 54032, 'Publication metadata observations are missing.', 1;
IF OBJECT_ID(N'dbo.PublicationCitationObservation', N'U') IS NULL
    THROW 54033, 'Publication citation observations are missing.', 1;
IF OBJECT_ID(N'dbo.TR_ApplicationPublication_NoOverwrite', N'TR') IS NULL
    THROW 54034, 'Publication no-overwrite enforcement is missing.', 1;
IF EXISTS
(
    SELECT expected.ConstraintName
    FROM (VALUES
        (N'PK_ApplicationPublication', N'ApplicationPublication', N'PK'),
        (N'PK_ApplicationPublicationSourceOccurrence', N'ApplicationPublicationSourceOccurrence', N'PK'),
        (N'PK_PublicationMetadataObservation', N'PublicationMetadataObservation', N'PK'),
        (N'PK_PublicationCitationObservation', N'PublicationCitationObservation', N'PK'),
        (N'UQ_ApplicationPublication_Identity', N'ApplicationPublication', N'UQ'),
        (N'UQ_ApplicationPublicationSourceOccurrence_Payload', N'ApplicationPublicationSourceOccurrence', N'UQ'),
        (N'UQ_PublicationMetadataObservation_Payload', N'PublicationMetadataObservation', N'UQ'),
        (N'UQ_PublicationCitationObservation_Payload', N'PublicationCitationObservation', N'UQ')
    ) AS expected(ConstraintName, TableName, ConstraintType)
    WHERE NOT EXISTS
    (
        SELECT 1
        FROM sys.key_constraints AS actual
        JOIN sys.indexes AS backing_index
          ON backing_index.object_id=actual.parent_object_id
         AND backing_index.index_id=actual.unique_index_id
        WHERE actual.name=expected.ConstraintName
          AND actual.parent_object_id=OBJECT_ID(N'dbo.' + expected.TableName)
          AND actual.type=expected.ConstraintType
          AND backing_index.is_unique=1
          AND backing_index.is_disabled=0
    )
)
    THROW 54039, 'A publication primary-key or uniqueness contract is missing.', 1;
IF EXISTS
(
    SELECT expected.ConstraintName
    FROM (VALUES
        (N'FK_ApplicationPublication_Application', N'ApplicationPublication', N'ApplicationId', N'Application', N'ApplicationId'),
        (N'FK_ApplicationPublication_ImportRun', N'ApplicationPublication', N'CreatedByImportRunId', N'ImportRun', N'ImportRunId'),
        (N'FK_ApplicationPublicationSourceOccurrence_Publication', N'ApplicationPublicationSourceOccurrence', N'ApplicationPublicationId', N'ApplicationPublication', N'ApplicationPublicationId'),
        (N'FK_ApplicationPublicationSourceOccurrence_Run', N'ApplicationPublicationSourceOccurrence', N'ImportRunId', N'ImportRun', N'ImportRunId'),
        (N'FK_PublicationMetadataObservation_Publication', N'PublicationMetadataObservation', N'ApplicationPublicationId', N'ApplicationPublication', N'ApplicationPublicationId'),
        (N'FK_PublicationMetadataObservation_Run', N'PublicationMetadataObservation', N'ImportRunId', N'ImportRun', N'ImportRunId'),
        (N'FK_PublicationCitationObservation_Publication', N'PublicationCitationObservation', N'ApplicationPublicationId', N'ApplicationPublication', N'ApplicationPublicationId'),
        (N'FK_PublicationCitationObservation_Run', N'PublicationCitationObservation', N'ImportRunId', N'ImportRun', N'ImportRunId')
    ) AS expected(ConstraintName, ParentTable, ParentColumn, ReferencedTable, ReferencedColumn)
    WHERE NOT EXISTS
    (
        SELECT 1
        FROM sys.foreign_keys AS actual
        WHERE actual.name=expected.ConstraintName
          AND actual.parent_object_id=OBJECT_ID(N'dbo.' + expected.ParentTable)
          AND actual.referenced_object_id=OBJECT_ID(N'dbo.' + expected.ReferencedTable)
          AND actual.is_disabled=0
          AND actual.is_not_trusted=0
          AND (SELECT COUNT(*) FROM sys.foreign_key_columns AS link WHERE link.constraint_object_id=actual.object_id)=1
          AND EXISTS
          (
              SELECT 1
              FROM sys.foreign_key_columns AS link
              JOIN sys.columns AS parent_column
                ON parent_column.object_id=link.parent_object_id
               AND parent_column.column_id=link.parent_column_id
              JOIN sys.columns AS referenced_column
                ON referenced_column.object_id=link.referenced_object_id
               AND referenced_column.column_id=link.referenced_column_id
              WHERE link.constraint_object_id=actual.object_id
                AND parent_column.name=expected.ParentColumn
                AND referenced_column.name=expected.ReferencedColumn
          )
    )
)
    THROW 54040, 'A publication foreign-key contract is missing.', 1;
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'UX_ApplicationPublication_Doi' AND object_id=OBJECT_ID(N'dbo.ApplicationPublication') AND is_unique=1 AND is_disabled=0 AND has_filter=1 AND filter_definition LIKE N'%Doi%IS NOT NULL%')
    THROW 54041, 'The filtered publication DOI uniqueness contract is missing.', 1;
IF EXISTS
(
    SELECT expected.ConstraintName
    FROM (VALUES
        (N'CK_ApplicationPublication_WorkKey', N'ApplicationPublication'),
        (N'CK_ApplicationPublication_Doi', N'ApplicationPublication'),
        (N'CK_ApplicationPublication_Link', N'ApplicationPublication'),
        (N'CK_ApplicationPublication_Year', N'ApplicationPublication'),
        (N'CK_ApplicationPublication_Status', N'ApplicationPublication'),
        (N'CK_ApplicationPublicationSourceOccurrence_Type', N'ApplicationPublicationSourceOccurrence'),
        (N'CK_ApplicationPublicationSourceOccurrence_Page', N'ApplicationPublicationSourceOccurrence'),
        (N'CK_ApplicationPublicationSourceOccurrence_Citation', N'ApplicationPublicationSourceOccurrence'),
        (N'CK_PublicationMetadataObservation_Source', N'PublicationMetadataObservation'),
        (N'CK_PublicationMetadataObservation_Json', N'PublicationMetadataObservation'),
        (N'CK_PublicationCitationObservation_Source', N'PublicationCitationObservation'),
        (N'CK_PublicationCitationObservation_Status', N'PublicationCitationObservation'),
        (N'CK_PublicationCitationObservation_Count', N'PublicationCitationObservation'),
        (N'CK_PublicationCitationObservation_StatusCount', N'PublicationCitationObservation'),
        (N'CK_PublicationCitationObservation_Evidence', N'PublicationCitationObservation')
    ) AS expected(ConstraintName, TableName)
    WHERE NOT EXISTS
    (
        SELECT 1 FROM sys.check_constraints AS actual
        WHERE actual.name=expected.ConstraintName
          AND actual.parent_object_id=OBJECT_ID(N'dbo.' + expected.TableName)
          AND actual.is_disabled=0
          AND actual.is_not_trusted=0
    )
)
    THROW 54042, 'A publication check constraint is missing, disabled, or untrusted.', 1;
IF OBJECT_ID(N'dbo.TR_ApplicationPublicationSourceOccurrence_AppendOnly', N'TR') IS NULL
    THROW 54043, 'The source occurrence append-only trigger is missing.', 1;
IF OBJECT_ID(N'dbo.TR_PublicationMetadataObservation_AppendOnly', N'TR') IS NULL
    THROW 54044, 'The metadata observation append-only trigger is missing.', 1;
IF OBJECT_ID(N'dbo.TR_PublicationCitationObservation_AppendOnly', N'TR') IS NULL
    THROW 54045, 'The citation observation append-only trigger is missing.', 1;

DECLARE @RuntimeRoleId int = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime');
IF @RuntimeRoleId IS NULL
    THROW 54035, 'The runtime role is missing.', 1;
IF EXISTS
(
    SELECT protected.TableName, denied.PermissionName
    FROM (VALUES
        (N'ApplicationPublication'),
        (N'ApplicationPublicationSourceOccurrence'),
        (N'PublicationMetadataObservation'),
        (N'PublicationCitationObservation')
    ) AS protected(TableName)
    CROSS JOIN (VALUES (N'SELECT'), (N'INSERT'), (N'UPDATE'), (N'DELETE')) AS denied(PermissionName)
    WHERE NOT EXISTS
    (
        SELECT 1
        FROM sys.database_permissions AS permission_row
        WHERE permission_row.grantee_principal_id = @RuntimeRoleId
          AND permission_row.major_id = OBJECT_ID(N'dbo.' + protected.TableName, N'U')
          AND permission_row.permission_name = denied.PermissionName
          AND permission_row.state = N'D'
    )
)
    THROW 54036, 'A publication table runtime denial is missing.', 1;

SET XACT_ABORT OFF;
BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallId uniqueidentifier = NEWID(),
            @ApplicantId uniqueidentifier = NEWID(),
            @ApplicationId uniqueidentifier = NEWID(),
            @RunId uniqueidentifier = NEWID(),
            @PublicationId uniqueidentifier = NEWID();
    INSERT dbo.FellowshipCall
        (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
    VALUES
        (@CallId, N'EHF-021-' + CONVERT(nvarchar(36), @CallId), N'Publication validator', 'DRAFT', SYSUTCDATETIME());
    INSERT dbo.Applicant (ApplicantId, LegalGivenNames, LegalFamilyName)
    VALUES (@ApplicantId, N'Publication', N'Validator');
    INSERT dbo.Application (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus)
    VALUES (@ApplicationId, @CallId, @ApplicantId, 'IMPORTED');
    INSERT dbo.ImportRun
        (ImportRunId, FellowshipCallId, ImportFingerprintSha256, ImporterVersion, RunStatus, StartedByIdentity)
    VALUES
        (@RunId, @CallId, HASHBYTES('SHA2_256', N'021 import'), '2026.4-publications', 'RUNNING', N'validator');
    INSERT dbo.ApplicationPublication
        (ApplicationPublicationId, ApplicationId, CreatedByImportRunId,
         PublicationIdentitySha256, ManifestWorkKey, Title, ResolutionStatus)
    VALUES
        (@PublicationId, @ApplicationId, @RunId, HASHBYTES('SHA2_256', N'021 publication'),
         'validator-work', N'Original title', 'RESOLVED');
    UPDATE dbo.ApplicationPublication
       SET Doi = '10.1000/validator', HttpLink = N'https://doi.org/10.1000/validator'
     WHERE ApplicationPublicationId = @PublicationId;
    IF NOT EXISTS
    (
        SELECT 1 FROM dbo.ApplicationPublication
        WHERE ApplicationPublicationId = @PublicationId
          AND Doi = '10.1000/validator'
          AND HttpLink = N'https://doi.org/10.1000/validator'
          AND Title = N'Original title'
    )
        THROW 54037, 'Blank publication values were not filled.', 1;
    BEGIN TRY
        UPDATE dbo.ApplicationPublication SET Title = N'Replacement title'
        WHERE ApplicationPublicationId = @PublicationId;
        THROW 54038, 'A non-blank publication value was overwritten.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() <> 54021 THROW;
    END CATCH;
    ROLLBACK TRANSACTION;
    SET XACT_ABORT ON;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    SET XACT_ABORT ON;
    THROW;
END CATCH;

-- Each append-only failure gets its own transaction because a trigger THROW
-- deliberately makes the current transaction uncommittable.
SET XACT_ABORT OFF;
BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallO uniqueidentifier=NEWID(), @ApplicantO uniqueidentifier=NEWID(),
            @ApplicationO uniqueidentifier=NEWID(), @RunO uniqueidentifier=NEWID(),
            @PublicationO uniqueidentifier=NEWID();
    INSERT dbo.FellowshipCall (FellowshipCallId,CallCode,DisplayName,CallStatus,ApplicationDeadlineUtc)
    VALUES (@CallO,N'EHF-021-O-'+CONVERT(nvarchar(36),@CallO),N'Occurrence validator','DRAFT',SYSUTCDATETIME());
    INSERT dbo.Applicant (ApplicantId,LegalGivenNames,LegalFamilyName) VALUES (@ApplicantO,N'Occurrence',N'Validator');
    INSERT dbo.Application (ApplicationId,FellowshipCallId,ApplicantId,ApplicationStatus) VALUES (@ApplicationO,@CallO,@ApplicantO,'IMPORTED');
    INSERT dbo.ImportRun (ImportRunId,FellowshipCallId,ImportFingerprintSha256,ImporterVersion,RunStatus,StartedByIdentity)
    VALUES (@RunO,@CallO,HASHBYTES('SHA2_256',N'021 occurrence run'),'2026.4-publications','RUNNING',N'validator');
    INSERT dbo.ApplicationPublication (ApplicationPublicationId,ApplicationId,CreatedByImportRunId,PublicationIdentitySha256,ManifestWorkKey,ResolutionStatus)
    VALUES (@PublicationO,@ApplicationO,@RunO,HASHBYTES('SHA2_256',N'021 occurrence publication'),'validator-occurrence','UNRESOLVED');
    INSERT dbo.ApplicationPublicationSourceOccurrence
        (ApplicationPublicationId,ImportRunId,SourceType,SourceLocatorSha256,SourcePage,RawCitation,PayloadSha256)
    VALUES (@PublicationO,@RunO,'DOSSIER',HASHBYTES('SHA2_256',N'021 locator'),1,N'Validator citation',HASHBYTES('SHA2_256',N'021 occurrence'));
    BEGIN TRY
        DELETE dbo.ApplicationPublicationSourceOccurrence WHERE ApplicationPublicationId=@PublicationO;
        THROW 54046, 'A publication source occurrence was deleted.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER()<>54022 THROW;
    END CATCH;
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    SET XACT_ABORT ON;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    SET XACT_ABORT ON;
    THROW;
END CATCH;

SET XACT_ABORT OFF;
BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallM uniqueidentifier=NEWID(), @ApplicantM uniqueidentifier=NEWID(),
            @ApplicationM uniqueidentifier=NEWID(), @RunM uniqueidentifier=NEWID(),
            @PublicationM uniqueidentifier=NEWID();
    INSERT dbo.FellowshipCall (FellowshipCallId,CallCode,DisplayName,CallStatus,ApplicationDeadlineUtc)
    VALUES (@CallM,N'EHF-021-M-'+CONVERT(nvarchar(36),@CallM),N'Metadata validator','DRAFT',SYSUTCDATETIME());
    INSERT dbo.Applicant (ApplicantId,LegalGivenNames,LegalFamilyName) VALUES (@ApplicantM,N'Metadata',N'Validator');
    INSERT dbo.Application (ApplicationId,FellowshipCallId,ApplicantId,ApplicationStatus) VALUES (@ApplicationM,@CallM,@ApplicantM,'IMPORTED');
    INSERT dbo.ImportRun (ImportRunId,FellowshipCallId,ImportFingerprintSha256,ImporterVersion,RunStatus,StartedByIdentity)
    VALUES (@RunM,@CallM,HASHBYTES('SHA2_256',N'021 metadata run'),'2026.4-publications','RUNNING',N'validator');
    INSERT dbo.ApplicationPublication (ApplicationPublicationId,ApplicationId,CreatedByImportRunId,PublicationIdentitySha256,ManifestWorkKey,ResolutionStatus)
    VALUES (@PublicationM,@ApplicationM,@RunM,HASHBYTES('SHA2_256',N'021 metadata publication'),'validator-metadata','UNRESOLVED');
    INSERT dbo.PublicationMetadataObservation
        (ApplicationPublicationId,ImportRunId,SourceCode,SourceIdentifier,MetadataJson,ObservedAtUtc,PayloadSha256)
    VALUES (@PublicationM,@RunM,'DOSSIER',N'validator-work',N'{}',SYSUTCDATETIME(),HASHBYTES('SHA2_256',N'021 metadata'));
    BEGIN TRY
        DELETE dbo.PublicationMetadataObservation WHERE ApplicationPublicationId=@PublicationM;
        THROW 54047, 'A publication metadata observation was deleted.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER()<>54023 THROW;
    END CATCH;
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    SET XACT_ABORT ON;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    SET XACT_ABORT ON;
    THROW;
END CATCH;

SET XACT_ABORT OFF;
BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @CallC uniqueidentifier=NEWID(), @ApplicantC uniqueidentifier=NEWID(),
            @ApplicationC uniqueidentifier=NEWID(), @RunC uniqueidentifier=NEWID(),
            @PublicationC uniqueidentifier=NEWID();
    INSERT dbo.FellowshipCall (FellowshipCallId,CallCode,DisplayName,CallStatus,ApplicationDeadlineUtc)
    VALUES (@CallC,N'EHF-021-C-'+CONVERT(nvarchar(36),@CallC),N'Citation validator','DRAFT',SYSUTCDATETIME());
    INSERT dbo.Applicant (ApplicantId,LegalGivenNames,LegalFamilyName) VALUES (@ApplicantC,N'Citation',N'Validator');
    INSERT dbo.Application (ApplicationId,FellowshipCallId,ApplicantId,ApplicationStatus) VALUES (@ApplicationC,@CallC,@ApplicantC,'IMPORTED');
    INSERT dbo.ImportRun (ImportRunId,FellowshipCallId,ImportFingerprintSha256,ImporterVersion,RunStatus,StartedByIdentity)
    VALUES (@RunC,@CallC,HASHBYTES('SHA2_256',N'021 citation run'),'2026.4-publications','RUNNING',N'validator');
    INSERT dbo.ApplicationPublication (ApplicationPublicationId,ApplicationId,CreatedByImportRunId,PublicationIdentitySha256,ManifestWorkKey,ResolutionStatus)
    VALUES (@PublicationC,@ApplicationC,@RunC,HASHBYTES('SHA2_256',N'021 citation publication'),'validator-citation','UNRESOLVED');
    INSERT dbo.PublicationCitationObservation
        (ApplicationPublicationId,ImportRunId,SourceCode,CitationCount,CitationStatus,EvidenceJson,ObservedAtUtc,PayloadSha256)
    VALUES (@PublicationC,@RunC,'GOOGLE_SCHOLAR',NULL,'MANUAL_REQUIRED',N'{}',NULL,HASHBYTES('SHA2_256',N'021 citation'));
    BEGIN TRY
        DELETE dbo.PublicationCitationObservation WHERE ApplicationPublicationId=@PublicationC;
        THROW 54048, 'A publication citation observation was deleted.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER()<>54024 THROW;
    END CATCH;
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    SET XACT_ABORT ON;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    SET XACT_ABORT ON;
    THROW;
END CATCH;

PRINT 'PASS 021 application publications';
