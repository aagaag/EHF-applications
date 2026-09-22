SET NOCOUNT ON;
IF OBJECT_ID(N'dbo.ListPendingPublicationReviews',N'P') IS NULL OR OBJECT_ID(N'dbo.RecordPendingPublicationReview',N'P') IS NULL THROW 54310,'Pending publication review procedures are missing.',1;
PRINT 'PASS 043 pending publication review queue';
