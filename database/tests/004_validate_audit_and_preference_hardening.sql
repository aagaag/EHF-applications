SET NOCOUNT ON;
SET XACT_ABORT OFF;

IF OBJECT_ID(N'dbo.IsAuditPayloadKeyProhibited', N'FN') IS NULL
    THROW 51400, 'The audit-payload key policy is missing.', 1;
IF OBJECT_ID(N'dbo.TR_AuditEvent_RejectSensitivePayload', N'TR') IS NULL
   OR OBJECT_ID(N'dbo.TR_UserPreference_ProcedureOnly', N'TR') IS NULL
   OR OBJECT_ID(N'dbo.SetUserPreference', N'P') IS NULL
    THROW 51401, 'A hardened audit or preference module is missing.', 1;

DECLARE @PreferenceExecutorId int =
    DATABASE_PRINCIPAL_ID(N'EHFPreferenceProcedureExecutor');
IF @PreferenceExecutorId IS NULL
    THROW 51406, 'The preference procedure execution principal is missing.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM sys.sql_modules
    WHERE object_id = OBJECT_ID(N'dbo.SetUserPreference', N'P')
      AND execute_as_principal_id = @PreferenceExecutorId
)
    THROW 51407, 'SetUserPreference has the wrong execution principal.', 1;

DECLARE @CreatedValidatorUser bit = 0;
DECLARE @IsImpersonated bit = 0;

BEGIN TRY
    CREATE USER EHFPreferenceDmlValidator WITHOUT LOGIN;
    GRANT INSERT, UPDATE, DELETE ON dbo.UserPreference
        TO EHFPreferenceDmlValidator;
    GRANT EXECUTE ON dbo.SetUserPreference
        TO EHFPreferenceDmlValidator;
    SET @CreatedValidatorUser = 1;

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

        DELETE @ProhibitedAuditPayload WHERE CaseName = @ProhibitedCaseName;

        -- ISOLATED EXPECTED FAILURE: prohibited audit payload aliases
        BEGIN TRANSACTION;
        BEGIN TRY
            INSERT dbo.AuditEvent
                (EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
            VALUES
                ('VALIDATOR_UNSAFE', N'validator', 'Validator', NEWID(),
                 @ProhibitedPayloadJson);
            THROW 51402, 'AuditEvent accepted a prohibited payload alias.', 1;
        END TRY
        BEGIN CATCH
            IF ERROR_NUMBER() = 51402 THROW;
            IF ERROR_NUMBER() <> 51032 THROW;
            IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        END CATCH;
    END;

    DECLARE @DirectPreferenceWriteRejected bit = 0;
    -- ISOLATED EXPECTED FAILURE: direct preference DML
    BEGIN TRANSACTION;
    EXECUTE AS USER = N'EHFPreferenceDmlValidator';
    SET @IsImpersonated = 1;
    IF HAS_PERMS_BY_NAME
       (N'EHFPreferenceProcedureExecutor', N'USER', N'IMPERSONATE') <> 0
    BEGIN
        REVERT;
        SET @IsImpersonated = 0;
        THROW 51408, 'The direct-DML principal can impersonate the procedure executor.', 1;
    END;
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
            SET @IsImpersonated = 0;
            IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
            THROW;
        END;
        SET @DirectPreferenceWriteRejected = 1;
    END CATCH;
    EXEC sys.sp_set_session_context
        @key = N'EHF.UserPreferenceProcedure', @value = NULL;
    REVERT;
    SET @IsImpersonated = 0;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;

    IF @DirectPreferenceWriteRejected <> 1
        THROW 51403, 'Caller-controlled session context enabled direct preference DML.', 1;

    -- SUCCESSFUL VALIDATOR WRITES (ROLLED BACK)
    BEGIN TRANSACTION;
    BEGIN TRY
        INSERT dbo.AuditEvent
            (EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
        VALUES
            ('VALIDATOR_SAFE', N'validator', 'Validator', NEWID(),
             N'{"applicationId":"00000000-0000-0000-0000-000000000001",'
             + N'"documentId":"00000000-0000-0000-0000-000000000002",'
             + N'"requestId":"00000000-0000-0000-0000-000000000003",'
             + N'"before":{"status":"DRAFT"},"after":{"status":"OPEN"}}');

        BEGIN TRY
            EXECUTE AS USER = N'EHFPreferenceDmlValidator';
            SET @IsImpersonated = 1;
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
            SET @IsImpersonated = 0;
        END TRY
        BEGIN CATCH
            IF @IsImpersonated = 1
            BEGIN
                REVERT;
                SET @IsImpersonated = 0;
            END;
            IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
            THROW;
        END CATCH;
    END TRY
    BEGIN CATCH
        IF @IsImpersonated = 1
        BEGIN
            REVERT;
            SET @IsImpersonated = 0;
        END;
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
        THROW;
    END CATCH;

    DECLARE @UserPreferenceId uniqueidentifier =
    (
        SELECT UserPreferenceId
        FROM dbo.UserPreference
        WHERE IdentityKey = N'validator-identity'
    );

    IF @UserPreferenceId IS NULL
        THROW 51404, 'SetUserPreference did not store the preference.', 1;
    IF NOT EXISTS
    (
        SELECT 1
        FROM dbo.AuditEvent
        WHERE EntityId = @UserPreferenceId
          AND EventType = 'USER_PREFERENCE_SET'
          AND JSON_VALUE(PayloadJson, '$.before.skin') IS NULL
          AND JSON_VALUE(PayloadJson, '$.after.skin') = 'soft-earth'
    )
        THROW 51405, 'SetUserPreference did not append before/after audit facts.', 1;

    ROLLBACK TRANSACTION;

    IF @CreatedValidatorUser = 1
    BEGIN
        DROP USER EHFPreferenceDmlValidator;
        SET @CreatedValidatorUser = 0;
    END;
END TRY
BEGIN CATCH
    IF @IsImpersonated = 1
    BEGIN
        EXEC sys.sp_set_session_context
            @key = N'EHF.UserPreferenceProcedure', @value = NULL;
        REVERT;
        SET @IsImpersonated = 0;
    END;
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    IF @CreatedValidatorUser = 1
    BEGIN
        DROP USER EHFPreferenceDmlValidator;
        SET @CreatedValidatorUser = 0;
    END;
    THROW;
END CATCH;

PRINT 'PASS 004 audit and preference hardening';
