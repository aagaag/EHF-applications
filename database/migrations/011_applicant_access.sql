SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE TABLE dbo.ApplicantInvitation
(
    ApplicantInvitationId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantInvitation_Id DEFAULT NEWSEQUENTIALID(),
    ApplicationId uniqueidentifier NOT NULL,
    InvitationTokenSha256 binary(32) NOT NULL,
    ExpiresAtUtc datetime2(7) NOT NULL,
    RevokedAtUtc datetime2(7) NULL,
    CreatedByIdentity nvarchar(255) NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantInvitation_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicantInvitation PRIMARY KEY (ApplicantInvitationId),
    CONSTRAINT FK_ApplicantInvitation_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT UQ_ApplicantInvitation_TokenHash UNIQUE (InvitationTokenSha256),
    CONSTRAINT CK_ApplicantInvitation_Expiry CHECK (ExpiresAtUtc > CreatedAtUtc),
    CONSTRAINT CK_ApplicantInvitation_Actor CHECK (LEN(CreatedByIdentity) > 0)
);

CREATE INDEX IX_ApplicantInvitation_Application
ON dbo.ApplicantInvitation (ApplicationId, ExpiresAtUtc);

CREATE TABLE dbo.ApplicantPreAuthContext
(
    ApplicantPreAuthContextId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantPreAuthContext_Id DEFAULT NEWSEQUENTIALID(),
    ApplicantInvitationId uniqueidentifier NULL,
    PreAuthContextSha256 binary(32) NOT NULL,
    ExpiresAtUtc datetime2(7) NOT NULL,
    ConsumedAtUtc datetime2(7) NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantPreAuthContext_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicantPreAuthContext PRIMARY KEY (ApplicantPreAuthContextId),
    CONSTRAINT FK_ApplicantPreAuthContext_Invitation FOREIGN KEY (ApplicantInvitationId)
        REFERENCES dbo.ApplicantInvitation (ApplicantInvitationId),
    CONSTRAINT UQ_ApplicantPreAuthContext_Hash UNIQUE (PreAuthContextSha256),
    CONSTRAINT CK_ApplicantPreAuthContext_Expiry CHECK (ExpiresAtUtc > CreatedAtUtc),
    CONSTRAINT CK_ApplicantPreAuthContext_Consumed CHECK
        (ConsumedAtUtc IS NULL OR ConsumedAtUtc >= CreatedAtUtc)
);

CREATE TABLE dbo.ApplicantVerificationChallenge
(
    ApplicantVerificationChallengeId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantVerificationChallenge_Id DEFAULT NEWSEQUENTIALID(),
    ApplicantInvitationId uniqueidentifier NOT NULL,
    VerificationCodeHmacSha256 binary(32) NOT NULL,
    ChallengeNonce binary(32) NOT NULL,
    ExpiresAtUtc datetime2(7) NOT NULL,
    AttemptCount tinyint NOT NULL
        CONSTRAINT DF_ApplicantVerificationChallenge_AttemptCount DEFAULT 0,
    MaxAttempts tinyint NOT NULL
        CONSTRAINT DF_ApplicantVerificationChallenge_MaxAttempts DEFAULT 5,
    ConsumedAtUtc datetime2(7) NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantVerificationChallenge_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicantVerificationChallenge PRIMARY KEY (ApplicantVerificationChallengeId),
    CONSTRAINT FK_ApplicantVerificationChallenge_Invitation FOREIGN KEY (ApplicantInvitationId)
        REFERENCES dbo.ApplicantInvitation (ApplicantInvitationId),
    CONSTRAINT UQ_ApplicantVerificationChallenge_CodeDigest UNIQUE
        (ApplicantInvitationId, VerificationCodeHmacSha256, ChallengeNonce),
    CONSTRAINT CK_ApplicantVerificationChallenge_Expiry CHECK (ExpiresAtUtc > CreatedAtUtc),
    CONSTRAINT CK_ApplicantVerificationChallenge_Attempts CHECK
        (MaxAttempts BETWEEN 1 AND 10 AND AttemptCount BETWEEN 0 AND MaxAttempts),
    CONSTRAINT CK_ApplicantVerificationChallenge_Consumed CHECK
        (ConsumedAtUtc IS NULL OR ConsumedAtUtc >= CreatedAtUtc)
);

CREATE INDEX IX_ApplicantVerificationChallenge_InvitationExpiry
ON dbo.ApplicantVerificationChallenge (ApplicantInvitationId, ExpiresAtUtc DESC);

CREATE TABLE dbo.ApplicantSession
(
    ApplicantSessionId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantSession_Id DEFAULT NEWSEQUENTIALID(),
    ApplicantInvitationId uniqueidentifier NOT NULL,
    ApplicationId uniqueidentifier NOT NULL,
    SessionTokenSha256 binary(32) NOT NULL,
    CsrfTokenSha256 binary(32) NOT NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantSession_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    LastSeenAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantSession_LastSeenAtUtc DEFAULT SYSUTCDATETIME(),
    IdleExpiresAtUtc datetime2(7) NOT NULL,
    AbsoluteExpiresAtUtc datetime2(7) NOT NULL,
    RevokedAtUtc datetime2(7) NULL,
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicantSession PRIMARY KEY (ApplicantSessionId),
    CONSTRAINT FK_ApplicantSession_Invitation FOREIGN KEY (ApplicantInvitationId)
        REFERENCES dbo.ApplicantInvitation (ApplicantInvitationId),
    CONSTRAINT FK_ApplicantSession_Application FOREIGN KEY (ApplicationId)
        REFERENCES dbo.Application (ApplicationId),
    CONSTRAINT UQ_ApplicantSession_TokenHash UNIQUE (SessionTokenSha256),
    CONSTRAINT UQ_ApplicantSession_CsrfHash UNIQUE (CsrfTokenSha256),
    CONSTRAINT CK_ApplicantSession_Expiry CHECK
        (CreatedAtUtc <= LastSeenAtUtc
         AND LastSeenAtUtc < IdleExpiresAtUtc
         AND IdleExpiresAtUtc <= AbsoluteExpiresAtUtc),
    CONSTRAINT CK_ApplicantSession_Revocation CHECK
        (RevokedAtUtc IS NULL OR RevokedAtUtc >= CreatedAtUtc)
);

CREATE INDEX IX_ApplicantSession_ApplicationExpiry
ON dbo.ApplicantSession (ApplicationId, AbsoluteExpiresAtUtc);

CREATE TABLE dbo.ApplicantRateLimitBucket
(
    ApplicantRateLimitBucketId uniqueidentifier NOT NULL
        CONSTRAINT DF_ApplicantRateLimitBucket_Id DEFAULT NEWSEQUENTIALID(),
    ScopeType varchar(20) NOT NULL,
    SubjectSha256 binary(32) NOT NULL,
    WindowStartedAtUtc datetime2(7) NOT NULL,
    WindowSeconds int NOT NULL,
    AttemptCount int NOT NULL,
    BlockedUntilUtc datetime2(7) NULL,
    CreatedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_ApplicantRateLimitBucket_CreatedAtUtc DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_ApplicantRateLimitBucket PRIMARY KEY (ApplicantRateLimitBucketId),
    CONSTRAINT UQ_ApplicantRateLimitBucket_SubjectWindow UNIQUE
        (ScopeType, SubjectSha256, WindowStartedAtUtc),
    CONSTRAINT CK_ApplicantRateLimitBucket_Scope CHECK
        (ScopeType IN ('INVITATION', 'IP', 'GLOBAL')),
    CONSTRAINT CK_ApplicantRateLimitBucket_Window CHECK
        (WindowSeconds BETWEEN 1 AND 86400 AND AttemptCount >= 0),
    CONSTRAINT CK_ApplicantRateLimitBucket_Block CHECK
        (BlockedUntilUtc IS NULL OR BlockedUntilUtc >= WindowStartedAtUtc)
);

DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantInvitation TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantPreAuthContext TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantVerificationChallenge TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantSession TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantRateLimitBucket TO EHFApplicationRuntime;
