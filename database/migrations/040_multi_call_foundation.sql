SET NOCOUNT ON;
SET XACT_ABORT ON;

/* Call ownership and access are made explicit here.  Application data is never
   selected by a slug: the application layer resolves a call through the
   procedure boundary below, then later call-aware procedures receive its ID. */
BEGIN TRANSACTION;

ALTER TABLE dbo.FellowshipCall ADD
    PublicSlug varchar(80) NULL,
    CompactTitle nvarchar(120) NULL,
    ApplicantReviewStatus varchar(20) NULL,
    InternalSelectionStatus varchar(20) NULL,
    InvitationsEnabled bit NULL,
    AnalysisProfileCode varchar(40) NULL;

UPDATE dbo.FellowshipCall
SET PublicSlug = LOWER(REPLACE(CallCode, N' ', N'-')),
    CompactTitle = LEFT(DisplayName, 120),
    ApplicantReviewStatus = CASE WHEN CallCode = N'EHF-2026' THEN 'OPEN' ELSE 'DISABLED' END,
    InternalSelectionStatus = CASE WHEN CallCode = N'EHF-2026' THEN 'OPEN' ELSE 'DISABLED' END,
    InvitationsEnabled = 0,
    AnalysisProfileCode = 'ehf-standard-v1'
WHERE PublicSlug IS NULL;

UPDATE dbo.FellowshipCall
SET PublicSlug = 'ehf-2026', CompactTitle = LEFT(DisplayName, 120),
    ApplicantReviewStatus = 'OPEN', InternalSelectionStatus = 'OPEN',
    InvitationsEnabled = 0, AnalysisProfileCode = 'ehf-standard-v1'
WHERE CallCode = N'EHF-2026';

IF EXISTS
(
    SELECT 1 FROM dbo.FellowshipCall
    WHERE PublicSlug IS NULL
       OR PublicSlug COLLATE Latin1_General_100_BIN2 LIKE '%[^a-z0-9-]%'
       OR LEN(PublicSlug) NOT BETWEEN 3 AND 80
       OR PublicSlug LIKE '-%' OR PublicSlug LIKE '%-' OR PublicSlug LIKE '%--%'
)
    THROW 54500, 'An existing fellowship call cannot be assigned a safe public slug.', 1;
IF EXISTS (SELECT 1 FROM dbo.FellowshipCall GROUP BY PublicSlug HAVING COUNT(*) > 1)
    THROW 54501, 'Existing fellowship calls do not map uniquely to public slugs.', 1;

ALTER TABLE dbo.FellowshipCall ALTER COLUMN PublicSlug varchar(80) NOT NULL;
ALTER TABLE dbo.FellowshipCall ALTER COLUMN CompactTitle nvarchar(120) NOT NULL;
ALTER TABLE dbo.FellowshipCall ALTER COLUMN ApplicantReviewStatus varchar(20) NOT NULL;
ALTER TABLE dbo.FellowshipCall ALTER COLUMN InternalSelectionStatus varchar(20) NOT NULL;
ALTER TABLE dbo.FellowshipCall ALTER COLUMN InvitationsEnabled bit NOT NULL;
ALTER TABLE dbo.FellowshipCall ALTER COLUMN AnalysisProfileCode varchar(40) NOT NULL;
ALTER TABLE dbo.FellowshipCall ADD
    CONSTRAINT UQ_FellowshipCall_PublicSlug UNIQUE (PublicSlug),
    CONSTRAINT CK_FellowshipCall_PublicSlug CHECK
    (PublicSlug COLLATE Latin1_General_100_BIN2 NOT LIKE '%[^a-z0-9-]%'
     AND LEN(PublicSlug) BETWEEN 3 AND 80
     AND PublicSlug NOT LIKE '-%' AND PublicSlug NOT LIKE '%-' AND PublicSlug NOT LIKE '%--%'),
    CONSTRAINT CK_FellowshipCall_ApplicantReviewStatus CHECK
        (ApplicantReviewStatus IN ('DISABLED','OPEN','CLOSED')),
    CONSTRAINT CK_FellowshipCall_InternalSelectionStatus CHECK
        (InternalSelectionStatus IN ('DISABLED','OPEN','LOCKED')),
    CONSTRAINT CK_FellowshipCall_AnalysisProfileCode CHECK
        (AnalysisProfileCode IN ('ehf-standard-v1'));

ALTER TABLE dbo.Applicant ADD FellowshipCallId uniqueidentifier NULL;
IF EXISTS
(
    SELECT application_row.ApplicantId
    FROM dbo.Application AS application_row
    GROUP BY application_row.ApplicantId
    HAVING COUNT(DISTINCT application_row.FellowshipCallId) > 1
)
    THROW 54502, 'An applicant is already linked to more than one fellowship call.', 1;

UPDATE applicant_row
SET FellowshipCallId = application_row.FellowshipCallId
FROM dbo.Applicant AS applicant_row
JOIN dbo.Application AS application_row ON application_row.ApplicantId = applicant_row.ApplicantId;

IF EXISTS (SELECT 1 FROM dbo.Applicant WHERE FellowshipCallId IS NULL)
    THROW 54503, 'Every applicant must belong to exactly one fellowship call.', 1;

ALTER TABLE dbo.Applicant ALTER COLUMN FellowshipCallId uniqueidentifier NOT NULL;
ALTER TABLE dbo.Applicant ADD
    CONSTRAINT FK_Applicant_FellowshipCall FOREIGN KEY (FellowshipCallId)
        REFERENCES dbo.FellowshipCall (FellowshipCallId),
    CONSTRAINT UQ_Applicant_CallApplicant UNIQUE (FellowshipCallId, ApplicantId);
ALTER TABLE dbo.Application ADD
    CONSTRAINT FK_Application_CallApplicant FOREIGN KEY (FellowshipCallId, ApplicantId)
        REFERENCES dbo.Applicant (FellowshipCallId, ApplicantId);

CREATE TABLE dbo.FellowshipCallGroupGrant
(
    FellowshipCallGroupGrantId uniqueidentifier NOT NULL
        CONSTRAINT DF_FellowshipCallGroupGrant_Id DEFAULT NEWSEQUENTIALID(),
    FellowshipCallId uniqueidentifier NOT NULL,
    GroupName nvarchar(128) NOT NULL,
    AccessRole varchar(16) NOT NULL,
    IsActive bit NOT NULL CONSTRAINT DF_FellowshipCallGroupGrant_IsActive DEFAULT 1,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_FellowshipCallGroupGrant_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    UpdatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_FellowshipCallGroupGrant_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_FellowshipCallGroupGrant PRIMARY KEY (FellowshipCallGroupGrantId),
    CONSTRAINT FK_FellowshipCallGroupGrant_Call FOREIGN KEY (FellowshipCallId)
        REFERENCES dbo.FellowshipCall (FellowshipCallId),
    CONSTRAINT UQ_FellowshipCallGroupGrant UNIQUE (FellowshipCallId, GroupName, AccessRole),
    CONSTRAINT CK_FellowshipCallGroupGrant_GroupName CHECK (LEN(LTRIM(RTRIM(GroupName))) > 0),
    CONSTRAINT CK_FellowshipCallGroupGrant_AccessRole CHECK (AccessRole IN ('ADMINISTER','READ'))
);

INSERT dbo.FellowshipCallGroupGrant (FellowshipCallId, GroupName, AccessRole)
SELECT FellowshipCallId, N'EHF-Administrators', 'ADMINISTER'
FROM dbo.FellowshipCall;
INSERT dbo.FellowshipCallGroupGrant (FellowshipCallId, GroupName, AccessRole)
SELECT FellowshipCallId, N'EHF-Trustees', 'READ'
FROM dbo.FellowshipCall WHERE CallCode = N'EHF-2026';

COMMIT TRANSACTION;

EXEC(N'
CREATE PROCEDURE dbo.ListAuthorizedFellowshipCalls
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    IF NULLIF(LTRIM(RTRIM(@ActorGroup)), N'''') IS NULL
        THROW 54510, ''An actor group is required.'', 1;
    SELECT call_row.FellowshipCallId, call_row.CallCode, call_row.PublicSlug,
           call_row.DisplayName, call_row.CompactTitle, call_row.CallStatus,
           call_row.ApplicantReviewStatus, call_row.InternalSelectionStatus,
           call_row.InvitationsEnabled, call_row.AnalysisProfileCode,
           call_row.ApplicationDeadlineUtc, call_row.ApplicantReviewDeadlineUtc,
           call_row.RowVersion,
           COUNT(application_row.ApplicationId) AS ApplicantCount,
           CONVERT(datetime2(7), NULL) AS LatestImportCompletedAtUtc,
           CONVERT(uniqueidentifier, NULL) AS ActivatedAnalysisEvidenceId,
           CONVERT(int, 0) AS ActiveShortlisterCount,
           CONVERT(varchar(20), ''UNAVAILABLE'') AS RosterState
    FROM dbo.FellowshipCall AS call_row
    JOIN dbo.FellowshipCallGroupGrant AS grant_row
      ON grant_row.FellowshipCallId = call_row.FellowshipCallId
     AND grant_row.GroupName = @ActorGroup AND grant_row.IsActive = 1
    LEFT JOIN dbo.Application AS application_row
      ON application_row.FellowshipCallId = call_row.FellowshipCallId
    GROUP BY call_row.FellowshipCallId, call_row.CallCode, call_row.PublicSlug,
             call_row.DisplayName, call_row.CompactTitle, call_row.CallStatus,
             call_row.ApplicantReviewStatus, call_row.InternalSelectionStatus,
             call_row.InvitationsEnabled, call_row.AnalysisProfileCode,
             call_row.ApplicationDeadlineUtc, call_row.ApplicantReviewDeadlineUtc,
             call_row.RowVersion
    ORDER BY call_row.ApplicationDeadlineUtc DESC, call_row.DisplayName;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetAuthorizedFellowshipCallBySlug
    @PublicSlug varchar(80), @ActorGroup nvarchar(128), @RequiredRole varchar(16)
AS
BEGIN
    SET NOCOUNT ON;
    IF @RequiredRole NOT IN (''READ'', ''ADMINISTER'')
       OR @PublicSlug IS NULL OR @PublicSlug LIKE ''%[^a-z0-9-]%''
       OR @PublicSlug LIKE ''-%'' OR @PublicSlug LIKE ''%-'' OR @PublicSlug LIKE ''%--%''
        THROW 54511, ''The requested call lookup is invalid.'', 1;
    SELECT call_row.FellowshipCallId, call_row.CallCode, call_row.PublicSlug,
           call_row.DisplayName, call_row.CompactTitle, call_row.CallStatus,
           call_row.ApplicantReviewStatus, call_row.InternalSelectionStatus,
           call_row.InvitationsEnabled, call_row.AnalysisProfileCode,
           call_row.ApplicationDeadlineUtc, call_row.ApplicantReviewDeadlineUtc,
           call_row.RowVersion
    FROM dbo.FellowshipCall AS call_row
    JOIN dbo.FellowshipCallGroupGrant AS grant_row
      ON grant_row.FellowshipCallId = call_row.FellowshipCallId
     AND grant_row.GroupName = @ActorGroup AND grant_row.IsActive = 1
     AND (grant_row.AccessRole = ''ADMINISTER'' OR @RequiredRole = ''READ'' AND grant_row.AccessRole = ''READ'')
    WHERE call_row.PublicSlug = @PublicSlug;
END;
');

EXEC(N'
CREATE PROCEDURE dbo.GetPublicFellowshipCallBySlug @PublicSlug varchar(80)
AS
BEGIN
    SET NOCOUNT ON;
    SELECT PublicSlug, CallCode, DisplayName, ApplicationDeadlineUtc,
           ApplicantReviewDeadlineUtc, ApplicantReviewStatus
    FROM dbo.FellowshipCall
    WHERE PublicSlug = @PublicSlug AND CallStatus IN (''OPEN'', ''CLOSED'')
      AND ApplicantReviewStatus <> ''DISABLED'';
END;
');

EXEC(N'
CREATE PROCEDURE dbo.CreateFellowshipCall
    @CallCode nvarchar(50), @PublicSlug varchar(80), @DisplayName nvarchar(200),
    @CompactTitle nvarchar(120), @ApplicationDeadlineUtc datetime2(7),
    @ActorIdentity nvarchar(255), @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    IF @ActorGroup <> N''EHF-Administrators'' OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
        THROW 54512, ''Administrator authorization is required.'', 1;
    IF @PublicSlug IS NULL OR @PublicSlug LIKE ''%[^a-z0-9-]%''
       OR @PublicSlug LIKE ''-%'' OR @PublicSlug LIKE ''%-'' OR @PublicSlug LIKE ''%--%''
        THROW 54513, ''The public slug is invalid.'', 1;
    BEGIN TRANSACTION;
    INSERT dbo.FellowshipCall
        (CallCode, PublicSlug, DisplayName, CompactTitle, CallStatus,
         ApplicationDeadlineUtc, ApplicantReviewStatus, InternalSelectionStatus,
         InvitationsEnabled, AnalysisProfileCode)
    VALUES (@CallCode, @PublicSlug, @DisplayName, @CompactTitle, ''DRAFT'',
            @ApplicationDeadlineUtc, ''DISABLED'', ''DISABLED'', 0, ''ehf-standard-v1'');
    DECLARE @CallId uniqueidentifier = (SELECT FellowshipCallId FROM dbo.FellowshipCall WHERE PublicSlug=@PublicSlug);
    INSERT dbo.FellowshipCallGroupGrant (FellowshipCallId, GroupName, AccessRole)
    VALUES (@CallId, N''EHF-Administrators'', ''ADMINISTER''), (@CallId, N''EHF-Trustees'', ''READ'');
    INSERT dbo.AuditEvent (FellowshipCallId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
    VALUES (@CallId, ''FELLOWSHIP_CALL_CREATED'', @ActorIdentity, ''FellowshipCall'', @CallId,
            (SELECT @PublicSlug AS publicSlug, ''DRAFT'' AS status FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));
    COMMIT TRANSACTION;
    EXEC dbo.GetAuthorizedFellowshipCallBySlug @PublicSlug=@PublicSlug, @ActorGroup=@ActorGroup, @RequiredRole=''ADMINISTER'';
END;
');

EXEC(N'
CREATE PROCEDURE dbo.TransitionFellowshipCall
    @FellowshipCallId uniqueidentifier, @CallStatus varchar(20),
    @ApplicantReviewStatus varchar(20), @InternalSelectionStatus varchar(20),
    @ActorIdentity nvarchar(255), @ActorGroup nvarchar(128), @ExpectedRowVersion binary(8)
AS
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    IF @ActorGroup <> N''EHF-Administrators'' OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
        THROW 54514, ''Administrator authorization is required.'', 1;
    IF @CallStatus NOT IN (''DRAFT'',''OPEN'',''CLOSED'',''ARCHIVED'')
       OR @ApplicantReviewStatus NOT IN (''DISABLED'',''OPEN'',''CLOSED'')
       OR @InternalSelectionStatus NOT IN (''DISABLED'',''OPEN'',''LOCKED'')
        THROW 54515, ''The requested lifecycle state is invalid.'', 1;
    BEGIN TRANSACTION;
    DECLARE @BeforeStatus varchar(20), @ActualRowVersion binary(8), @Slug varchar(80);
    SELECT @BeforeStatus=CallStatus, @ActualRowVersion=RowVersion, @Slug=PublicSlug
    FROM dbo.FellowshipCall WITH (UPDLOCK,HOLDLOCK) WHERE FellowshipCallId=@FellowshipCallId;
    IF @BeforeStatus IS NULL THROW 54516, ''The fellowship call does not exist.'', 1;
    IF @ActualRowVersion <> @ExpectedRowVersion THROW 54517, ''The fellowship call changed before this update.'', 1;
    IF @BeforeStatus = ''ARCHIVED'' OR (@BeforeStatus = ''DRAFT'' AND @CallStatus NOT IN (''DRAFT'',''OPEN'',''ARCHIVED''))
       OR (@BeforeStatus = ''OPEN'' AND @CallStatus NOT IN (''OPEN'',''CLOSED'',''ARCHIVED''))
       OR (@BeforeStatus = ''CLOSED'' AND @CallStatus NOT IN (''CLOSED'',''ARCHIVED''))
        THROW 54518, ''The lifecycle transition is not permitted.'', 1;
    UPDATE dbo.FellowshipCall SET CallStatus=@CallStatus,
        ApplicantReviewStatus=@ApplicantReviewStatus,
        InternalSelectionStatus=@InternalSelectionStatus, UpdatedAtUtc=SYSUTCDATETIME()
    WHERE FellowshipCallId=@FellowshipCallId;
    INSERT dbo.AuditEvent (FellowshipCallId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
    VALUES (@FellowshipCallId, ''FELLOWSHIP_CALL_TRANSITIONED'', @ActorIdentity, ''FellowshipCall'', @FellowshipCallId,
            (SELECT @BeforeStatus AS beforeStatus, @CallStatus AS afterStatus FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));
    COMMIT TRANSACTION;
    EXEC dbo.GetAuthorizedFellowshipCallBySlug @PublicSlug=@Slug, @ActorGroup=@ActorGroup, @RequiredRole=''ADMINISTER'';
END;
');

EXEC(N'
CREATE PROCEDURE dbo.SetFellowshipCallGroupGrant
    @FellowshipCallId uniqueidentifier, @GroupName nvarchar(128), @AccessRole varchar(16),
    @IsActive bit, @ActorIdentity nvarchar(255), @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    IF @ActorGroup <> N''EHF-Administrators'' OR NULLIF(LTRIM(RTRIM(@ActorIdentity)), N'''') IS NULL
        THROW 54519, ''Administrator authorization is required.'', 1;
    IF NULLIF(LTRIM(RTRIM(@GroupName)), N'''') IS NULL OR @AccessRole NOT IN (''ADMINISTER'', ''READ'')
        THROW 54520, ''The call grant is invalid.'', 1;
    IF NOT EXISTS (SELECT 1 FROM dbo.FellowshipCall WHERE FellowshipCallId=@FellowshipCallId)
        THROW 54521, ''The fellowship call does not exist.'', 1;
    BEGIN TRANSACTION;
    IF EXISTS (SELECT 1 FROM dbo.FellowshipCallGroupGrant WHERE FellowshipCallId=@FellowshipCallId AND GroupName=@GroupName AND AccessRole=@AccessRole)
        UPDATE dbo.FellowshipCallGroupGrant SET IsActive=@IsActive, UpdatedAtUtc=SYSUTCDATETIME()
        WHERE FellowshipCallId=@FellowshipCallId AND GroupName=@GroupName AND AccessRole=@AccessRole;
    ELSE
        INSERT dbo.FellowshipCallGroupGrant (FellowshipCallId, GroupName, AccessRole, IsActive)
        VALUES (@FellowshipCallId, @GroupName, @AccessRole, @IsActive);
    INSERT dbo.AuditEvent (FellowshipCallId, EventType, ActorIdentity, EntityType, EntityId, PayloadJson)
    VALUES (@FellowshipCallId, ''FELLOWSHIP_CALL_GRANT_CHANGED'', @ActorIdentity, ''FellowshipCall'', @FellowshipCallId,
            (SELECT @GroupName AS groupName, @AccessRole AS accessRole, @IsActive AS isActive FOR JSON PATH, WITHOUT_ARRAY_WRAPPER));
    COMMIT TRANSACTION;
END;
');

GRANT EXECUTE ON dbo.ListAuthorizedFellowshipCalls TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetAuthorizedFellowshipCallBySlug TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.GetPublicFellowshipCallBySlug TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.CreateFellowshipCall TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.TransitionFellowshipCall TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.SetFellowshipCallGroupGrant TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.FellowshipCallGroupGrant TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.Applicant TO EHFApplicationRuntime;

PRINT 'PASS 040 multi-call foundation';
