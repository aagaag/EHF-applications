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

BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @SafeAuditEventId uniqueidentifier = NEWID();
    INSERT dbo.AuditEvent
        (AuditEventId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
    VALUES
        (@SafeAuditEventId, 'VALIDATOR_SAFE', N'validator', 'Validator', NEWID(),
         N'{"before":{"status":"DRAFT"},"after":{"status":"OPEN"}}');

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

    BEGIN TRY
        INSERT dbo.AuditEvent
            (EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
        VALUES
            ('VALIDATOR_UNSAFE', N'validator', 'Validator', NEWID(),
             N'{"after":{"access_token":"prohibited"}}');
        THROW 51304, 'AuditEvent accepted a prohibited payload field.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() = 51304 THROW;
        IF ERROR_NUMBER() <> 51032 THROW;
    END CATCH;

    BEGIN TRY
        INSERT dbo.UserPreference
            (IdentityKey, Email, DisplayName, Skin,
             InvertColors, CompactDensity, ReduceMotion)
        VALUES
            (N'direct-validator', N'direct@example.invalid', N'Direct validator',
             'default', 0, 0, 0);
        THROW 51305, 'UserPreference accepted direct DML.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() = 51305 THROW;
        IF ERROR_NUMBER() <> 51033 THROW;
    END CATCH;

    EXEC dbo.SetUserPreference
        @IdentityKey = N'validator-identity',
        @Email = N'validator@example.invalid',
        @DisplayName = N'Validator identity',
        @Skin = 'soft-earth',
        @InvertColors = 1,
        @CompactDensity = 0,
        @ReduceMotion = 1,
        @ActorIdentity = N'validator-identity';

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
