SET NOCOUNT ON;
SET XACT_ABORT ON;

REVOKE EXECUTE ON dbo.RecordApplicationPublicationReview FROM EHFApplicationRuntime;

PRINT 'PASS 048 publication review permission';
