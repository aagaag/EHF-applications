SET NOCOUNT ON;
SET XACT_ABORT OFF;

IF OBJECT_ID(N'dbo.AuditEvent', N'U') IS NULL
   OR OBJECT_ID(N'dbo.UserPreference', N'U') IS NULL
    THROW 51300, 'Audit or preference table is missing.', 1;
IF OBJECT_ID(N'dbo.TR_AuditEvent_AppendOnly', N'TR') IS NULL
   OR OBJECT_ID(N'dbo.TR_AuditEvent_RejectSensitivePayload', N'TR') IS NULL
   OR OBJECT_ID(N'dbo.TR_UserPreference_ProcedureOnly', N'TR') IS NULL
    THROW 51301, 'An audit or preference mutation guard is missing.', 1;
IF OBJECT_ID(N'dbo.SetApplicationStatus', N'P') IS NULL
   OR OBJECT_ID(N'dbo.SetUserPreference', N'P') IS NULL
    THROW 51302, 'An audited mutation procedure is missing.', 1;
IF OBJECT_ID(N'dbo.IsAuditPayloadKeyProhibited', N'FN') IS NULL
    THROW 51310, 'The audit-payload key policy is missing.', 1;

BEGIN TRANSACTION;
BEGIN TRY
    CREATE USER EHFPreferenceDmlValidator WITHOUT LOGIN;
    GRANT INSERT, UPDATE, DELETE ON dbo.UserPreference
        TO EHFPreferenceDmlValidator;
    GRANT EXECUTE ON dbo.SetUserPreference
        TO EHFPreferenceDmlValidator;

    DECLARE @SafeAuditEventId uniqueidentifier = NEWID();
    INSERT dbo.AuditEvent
        (AuditEventId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
    VALUES
        (@SafeAuditEventId, 'VALIDATOR_SAFE', N'validator', 'Validator', NEWID(),
         N'{"applicationId":"00000000-0000-0000-0000-000000000001",'
         + N'"documentId":"00000000-0000-0000-0000-000000000002",'
         + N'"requestId":"00000000-0000-0000-0000-000000000003",'
         + N'"before":{"status":"DRAFT"},"after":{"status":"OPEN"}}');

    BEGIN TRY
        UPDATE dbo.AuditEvent
        SET EventType = 'MUTATED'
        WHERE AuditEventId = @SafeAuditEventId;
        THROW 51303, 'AuditEvent allowed an update.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() = 51303 THROW;
        IF ERROR_NUMBER() <> 51031 THROW;
    END CATCH;

    DECLARE @ProhibitedAuditPayload TABLE
    (
        CaseName sysname NOT NULL PRIMARY KEY,
        PayloadJson nvarchar(max) NOT NULL
    );
    INSERT @ProhibitedAuditPayload (CaseName, PayloadJson)
    VALUES
        (N'access_token', N'{"after":{"access_token":"prohibited"}}'),
        (N'apiToken', N'{"after":{"before":{"apiToken":"prohibited"}}}'),
        (N'API-TOKEN', N'{"after":{"API-TOKEN":"prohibited"}}'),
        (N'clientSecret', N'{"after":{"clientSecret":"prohibited"}}'),
        (N'client_secret', N'{"after":{"client_secret":"prohibited"}}'),
        (N'otpValue', N'{"after":{"otpValue":"prohibited"}}'),
        (N'otp.value', N'{"after":{"otp.value":"prohibited"}}'),
        (N'resumeDocument', N'{"after":{"resumeDocument":"prohibited"}}'),
        (N'resume-document', N'{"after":{"resume-document":"prohibited"}}'),
        (N'incomingRequestBody', N'{"after":{"incomingRequestBody":"prohibited"}}'),
        (N'incoming/request/body', N'{"after":{"incoming/request/body":"prohibited"}}'),
        (N'credentialBlob', N'{"after":{"credentialBlob":"prohibited"}}'),
        (N'rawFileBytes', N'{"after":{"rawFileBytes":"prohibited"}}'),
        (N'unexpectedMetadata', N'{"after":{"unexpectedMetadata":"prohibited"}}');

    DECLARE @ProhibitedCaseName sysname;
    DECLARE @ProhibitedPayloadJson nvarchar(max);
    WHILE EXISTS (SELECT 1 FROM @ProhibitedAuditPayload)
    BEGIN
        SELECT TOP (1)
            @ProhibitedCaseName = CaseName,
            @ProhibitedPayloadJson = PayloadJson
        FROM @ProhibitedAuditPayload
        ORDER BY CaseName;

        BEGIN TRY
            INSERT dbo.AuditEvent
                (EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
            VALUES
                ('VALIDATOR_UNSAFE', N'validator', 'Validator', NEWID(),
                 @ProhibitedPayloadJson);
            THROW 51304, 'AuditEvent accepted a prohibited payload alias.', 1;
        END TRY
        BEGIN CATCH
            IF ERROR_NUMBER() = 51304 THROW;
            IF ERROR_NUMBER() <> 51032 THROW;
        END CATCH;

        DELETE @ProhibitedAuditPayload WHERE CaseName = @ProhibitedCaseName;
    END;

    DECLARE @DirectPreferenceWriteRejected bit = 0;
    EXECUTE AS USER = N'EHFPreferenceDmlValidator';
    EXEC sys.sp_set_session_context
        @key = N'EHF.UserPreferenceProcedure', @value = 1;
    BEGIN TRY
        INSERT dbo.UserPreference
            (IdentityKey, Email, DisplayName, Skin,
             InvertColors, CompactDensity, ReduceMotion)
        VALUES
            (N'direct-validator', N'direct@example.invalid', N'Direct validator',
             'default', 0, 0, 0);
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() <> 51033
        BEGIN
            EXEC sys.sp_set_session_context
                @key = N'EHF.UserPreferenceProcedure', @value = NULL;
            REVERT;
            THROW;
        END;
        SET @DirectPreferenceWriteRejected = 1;
    END CATCH;
    EXEC sys.sp_set_session_context
        @key = N'EHF.UserPreferenceProcedure', @value = NULL;
    REVERT;

    IF @DirectPreferenceWriteRejected <> 1
        THROW 51305, 'Caller-controlled session context enabled direct preference DML.', 1;

    EXECUTE AS USER = N'EHFPreferenceDmlValidator';
    BEGIN TRY
        EXEC dbo.SetUserPreference
            @IdentityKey = N'validator-identity',
            @Email = N'validator@example.invalid',
            @DisplayName = N'Validator identity',
            @Skin = 'soft-earth',
            @InvertColors = 1,
            @CompactDensity = 0,
            @ReduceMotion = 1,
            @ActorIdentity = N'validator-identity';
        REVERT;
    END TRY
    BEGIN CATCH
        REVERT;
        THROW;
    END CATCH;

    DECLARE @UserPreferenceId uniqueidentifier =
    (
        SELECT UserPreferenceId
        FROM dbo.UserPreference
        WHERE IdentityKey = N'validator-identity'
    );

    IF @UserPreferenceId IS NULL
        THROW 51306, 'SetUserPreference did not store the preference.', 1;
    IF NOT EXISTS
    (
        SELECT 1
        FROM dbo.AuditEvent
        WHERE EntityId = @UserPreferenceId
          AND EventType = 'USER_PREFERENCE_SET'
          AND JSON_VALUE(PayloadJson, '$.before.skin') IS NULL
          AND JSON_VALUE(PayloadJson, '$.after.skin') = 'soft-earth'
    )
        THROW 51307, 'SetUserPreference did not append before/after audit facts.', 1;

    DECLARE @FellowshipCallId uniqueidentifier = NEWID();
    DECLARE @ApplicantId uniqueidentifier = NEWID();
    DECLARE @ApplicationId uniqueidentifier = NEWID();
    DECLARE @ApplicationRowVersion binary(8);

    INSERT dbo.FellowshipCall
        (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
    VALUES
        (@FellowshipCallId, N'AUDIT-VALIDATOR', N'Audit validator', 'DRAFT',
         CONVERT(datetime2(7), '2026-08-31T23:59:59'));
    INSERT dbo.Applicant (ApplicantId, LegalGivenNames, LegalFamilyName)
    VALUES (@ApplicantId, N'Synthetic', N'Audit');
    INSERT dbo.Application
        (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus)
    VALUES
        (@ApplicationId, @FellowshipCallId, @ApplicantId, 'DRAFT');
    SELECT @ApplicationRowVersion = RowVersion
    FROM dbo.Application
    WHERE ApplicationId = @ApplicationId;

    EXEC dbo.SetApplicationStatus
        @ApplicationId = @ApplicationId,
        @NewStatus = 'IN_REVIEW',
        @ActorIdentity = N'validator-identity',
        @ExpectedRowVersion = @ApplicationRowVersion;

    IF NOT EXISTS
    (
        SELECT 1
        FROM dbo.Application
        WHERE ApplicationId = @ApplicationId
          AND ApplicationStatus = 'IN_REVIEW'
    )
        THROW 51308, 'SetApplicationStatus did not update the application.', 1;
    IF NOT EXISTS
    (
        SELECT 1
        FROM dbo.AuditEvent
        WHERE ApplicationId = @ApplicationId
          AND EventType = 'APPLICATION_STATUS_CHANGED'
          AND JSON_VALUE(PayloadJson, '$.before.status') = 'DRAFT'
          AND JSON_VALUE(PayloadJson, '$.after.status') = 'IN_REVIEW'
    )
        THROW 51309, 'SetApplicationStatus did not append before/after audit facts.', 1;

    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    EXEC sys.sp_set_session_context
        @key = N'EHF.UserPreferenceProcedure', @value = NULL;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

PRINT 'PASS 003 audit and preferences';
