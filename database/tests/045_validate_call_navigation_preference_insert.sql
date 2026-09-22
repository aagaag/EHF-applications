SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRANSACTION;
EXEC dbo.SetCallNavigationPreference
    @IdentityKey = N'validator-call-navigation-insert',
    @Email = N'validator-insert@example.invalid',
    @DisplayName = N'Validator Insert',
    @DefaultCallMode = 'resume-last-opened',
    @LastFellowshipCallId = NULL,
    @ActorIdentity = N'validator-call-navigation-insert';
IF NOT EXISTS
(
    SELECT 1 FROM dbo.UserPreference
    WHERE IdentityKey = N'validator-call-navigation-insert'
      AND Skin = 'default'
      AND InvertColors = 0
      AND CompactDensity = 0
      AND ReduceMotion = 0
      AND DefaultCallMode = 'resume-last-opened'
)
    THROW 54620, 'A first-time call navigation preference did not preserve appearance defaults.', 1;
ROLLBACK TRANSACTION;

PRINT 'PASS 045 call navigation preference insert';
