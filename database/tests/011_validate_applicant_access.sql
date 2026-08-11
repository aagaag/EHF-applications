SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.ApplicantInvitation', N'U') IS NULL
    THROW 52211, 'The applicant invitation table is missing.', 1;
IF OBJECT_ID(N'dbo.ApplicantVerificationChallenge', N'U') IS NULL
    THROW 52212, 'The applicant verification challenge table is missing.', 1;
IF OBJECT_ID(N'dbo.ApplicantPreAuthContext', N'U') IS NULL
    THROW 52218, 'The applicant pre-auth context table is missing.', 1;
IF OBJECT_ID(N'dbo.ApplicantSession', N'U') IS NULL
    THROW 52213, 'The applicant session table is missing.', 1;
IF OBJECT_ID(N'dbo.ApplicantRateLimitBucket', N'U') IS NULL
    THROW 52214, 'The applicant rate-limit table is missing.', 1;
IF COL_LENGTH(N'dbo.ApplicantInvitation', N'InvitationToken') IS NOT NULL
    THROW 52215, 'A cleartext invitation token column is forbidden.', 1;
IF COL_LENGTH(N'dbo.ApplicantVerificationChallenge', N'VerificationCode') IS NOT NULL
    THROW 52216, 'A cleartext verification code column is forbidden.', 1;
IF COL_LENGTH(N'dbo.ApplicantSession', N'SessionToken') IS NOT NULL
    THROW 52217, 'A cleartext session token column is forbidden.', 1;

PRINT 'PASS 011 applicant access';
