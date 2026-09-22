SET NOCOUNT ON;
SET XACT_ABORT ON;
EXEC(N'
CREATE PROCEDURE dbo.ListPendingPublicationReviews @ActorGroup nvarchar(128)
AS BEGIN
 IF @ActorGroup NOT IN (N''EHF-Administrators'',N''EHF-Trustees'') THROW 54301,''Internal authorization is required.'',1;
 SELECT p.ApplicationPublicationId,COALESCE(JSON_VALUE(i.SnapshotJson,''$.fullName''),CONCAT(a.LegalGivenNames,N'' '',a.LegalFamilyName)),p.AuthorsText,p.Title,p.JournalText,p.VolumeText,p.PagesText,p.PublicationYear,p.Doi,p.HttpLink,s.RawCitation,p.ResolutionStatus
 FROM dbo.ApplicationPublication p JOIN dbo.Application x ON x.ApplicationId=p.ApplicationId JOIN dbo.Applicant a ON a.ApplicantId=x.ApplicantId
 OUTER APPLY(SELECT TOP(1) SnapshotJson FROM dbo.ApplicationSectionVersion WHERE ApplicationId=x.ApplicationId AND SectionCode=''identity'' ORDER BY VersionNumber DESC) i
 OUTER APPLY(SELECT TOP(1) RawCitation FROM dbo.ApplicationPublicationSourceOccurrence WHERE ApplicationPublicationId=p.ApplicationPublicationId ORDER BY RecordedAtUtc DESC,ApplicationPublicationSourceOccurrenceId DESC) s
 OUTER APPLY(SELECT TOP(1) ReviewDisposition FROM dbo.ApplicationPublicationReview WHERE ApplicationPublicationId=p.ApplicationPublicationId ORDER BY RecordedAtUtc DESC,ApplicationPublicationReviewId DESC) r
 WHERE r.ReviewDisposition = ''PENDING_REVIEW'' ORDER BY a.LegalFamilyName,a.LegalGivenNames,p.Title,p.ApplicationPublicationId;
END;');
EXEC(N'
CREATE PROCEDURE dbo.RecordPendingPublicationReview @ApplicationPublicationId uniqueidentifier,@ReviewDisposition varchar(32),@ReviewerIdentity nvarchar(255),@ActorGroup nvarchar(128)
AS BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 IF @ActorGroup NOT IN(N''EHF-Administrators'',N''EHF-Trustees'') THROW 54302,''Internal authorization is required.'',1;
 IF @ReviewDisposition NOT IN(''PUBLISHED'',''ACCEPTED_PREPRINT'',''NON_PUBLICATION'') THROW 54303,''The review disposition is invalid.'',1;
 BEGIN TRY
  BEGIN TRANSACTION;
  DECLARE @Latest varchar(32),@ResolutionStatus varchar(20),@EvidenceJson nvarchar(max);
  SELECT @Latest=r.ReviewDisposition,@ResolutionStatus=p.ResolutionStatus
  FROM dbo.ApplicationPublication p WITH (UPDLOCK, HOLDLOCK)
  OUTER APPLY(SELECT TOP(1) ReviewDisposition FROM dbo.ApplicationPublicationReview WHERE ApplicationPublicationId=p.ApplicationPublicationId ORDER BY RecordedAtUtc DESC,ApplicationPublicationReviewId DESC) r
  WHERE p.ApplicationPublicationId=@ApplicationPublicationId;
  IF @Latest IS NULL OR @Latest <> ''PENDING_REVIEW'' THROW 54304,''The publication is no longer pending review.'',1;
  IF @ReviewDisposition IN(''PUBLISHED'',''ACCEPTED_PREPRINT'') AND @ResolutionStatus <> ''RESOLVED''
  BEGIN
   EXEC sys.sp_set_session_context @key=N''EHFPublicationPromotion'',@value=1;
   UPDATE dbo.ApplicationPublication SET ResolutionStatus = ''RESOLVED'' WHERE ApplicationPublicationId=@ApplicationPublicationId;
   EXEC sys.sp_set_session_context @key=N''EHFPublicationPromotion'',@value=NULL;
  END;
  SELECT @EvidenceJson=(SELECT N''internal-pending-paper-review'' AS source,@ActorGroup AS actorGroup,@ReviewDisposition AS action FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
  EXEC dbo.RecordApplicationPublicationReview @ApplicationPublicationId=@ApplicationPublicationId,@ReviewDisposition=@ReviewDisposition,@ReviewerIdentity=@ReviewerIdentity,@ReviewReason=N''Rapid internal pending-paper classification.'',@EvidenceJson=@EvidenceJson;
  COMMIT TRANSACTION;
 END TRY
 BEGIN CATCH
  EXEC sys.sp_set_session_context @key=N''EHFPublicationPromotion'',@value=NULL;
  IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
  THROW;
 END CATCH;
END;');
GRANT EXECUTE ON dbo.ListPendingPublicationReviews TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.RecordPendingPublicationReview TO EHFApplicationRuntime;
