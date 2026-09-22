SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CallId uniqueidentifier =
    (SELECT TOP (1) FellowshipCallId FROM dbo.FellowshipCall ORDER BY ApplicationDeadlineUtc DESC);
BEGIN TRANSACTION;
EXEC dbo.SetCallNavigationPreference
    @IdentityKey = N'validator-call-navigation-audit',
    @Email = N'validator-audit@example.invalid',
    @DisplayName = N'Validator Audit',
    @DefaultCallMode = 'latest-application-deadline',
    @LastFellowshipCallId = @CallId,
    @ActorIdentity = N'validator-call-navigation-audit';
IF NOT EXISTS
(
    SELECT 1 FROM dbo.AuditEvent
    WHERE EventType = 'CALL_NAVIGATION_PREFERENCE_SET'
      AND ActorIdentity = N'validator-call-navigation-audit'
      AND JSON_VALUE(PayloadJson, '$.after.status') = 'latest-application-deadline'
      AND JSON_VALUE(PayloadJson, '$.after.callId') = CONVERT(nvarchar(36), @CallId)
)
    THROW 54630, 'The call navigation audit event is missing or malformed.', 1;
ROLLBACK TRANSACTION;

PRINT 'PASS 046 call navigation audit payload';
