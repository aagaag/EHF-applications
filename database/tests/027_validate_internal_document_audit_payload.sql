SET NOCOUNT ON;
SET XACT_ABORT ON;

IF dbo.IsAuditPayloadKeyProhibited(N'purpose') <> 0
    THROW 54200, 'The document-access audit purpose is not allowlisted.', 1;
IF dbo.IsAuditPayloadKeyProhibited(N'access-purpose') <> 1
    THROW 54201, 'An unapproved audit payload key was accepted.', 1;
IF dbo.IsAuditPayloadKeyProhibited(N'email') <> 1
    THROW 54202, 'A sensitive audit payload key was accepted.', 1;

BEGIN TRANSACTION;
INSERT dbo.AuditEvent
    (EventType,ActorIdentity,EntityType,EntityId,PayloadJson)
VALUES
    ('INTERNAL_DOCUMENT_ACCESS_VALIDATED',N'validator','DocumentVersion',NEWID(),
     (SELECT N'EHF-Trustees' AS actorGroup,N'VIEW' AS purpose,N'SUCCEEDED' AS outcome
      FOR JSON PATH,WITHOUT_ARRAY_WRAPPER));
IF @@ROWCOUNT <> 1
    THROW 54203, 'The safe document-access audit payload was not recorded.', 1;
ROLLBACK TRANSACTION;

PRINT 'PASS 027 internal document audit payload';
