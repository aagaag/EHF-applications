SET NOCOUNT ON;
SET XACT_ABORT ON;

CREATE TABLE dbo.CallSecondStageSelection
(
    FellowshipCallId uniqueidentifier NOT NULL,
    ApplicationId uniqueidentifier NOT NULL,
    IsSelected bit NOT NULL CONSTRAINT DF_CallSecondStageSelection_Selected DEFAULT 1,
    ModifiedByIdentity nvarchar(255) NOT NULL,
    RecordedAtUtc datetime2(7) NOT NULL CONSTRAINT DF_CallSecondStageSelection_Recorded DEFAULT SYSUTCDATETIME(),
    RowVersion rowversion NOT NULL,
    CONSTRAINT PK_CallSecondStageSelection PRIMARY KEY (FellowshipCallId, ApplicationId),
    CONSTRAINT FK_CallSecondStageSelection_Application FOREIGN KEY (FellowshipCallId, ApplicationId)
        REFERENCES dbo.Application (FellowshipCallId, ApplicationId),
    CONSTRAINT CK_CallSecondStageSelection_Actor CHECK (LEN(ModifiedByIdentity) > 0)
);

EXEC(N'
CREATE OR ALTER PROCEDURE dbo.GetCallSecondStageSelections
    @FellowshipCallId uniqueidentifier,
    @ActorGroup nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (
        SELECT 1 FROM dbo.FellowshipCallGroupGrant
        WHERE FellowshipCallId = @FellowshipCallId
          AND GroupName = @ActorGroup AND IsActive = 1
          AND AccessRole IN (''READ'',''ADMINISTER'')
    ) THROW 55101, ''The call is unavailable.'', 1;
    SELECT CONVERT(nvarchar(36), ApplicationId)
    FROM dbo.CallSecondStageSelection
    WHERE FellowshipCallId = @FellowshipCallId AND IsSelected = 1
    ORDER BY ApplicationId;
END;
');

EXEC(N'
CREATE OR ALTER PROCEDURE dbo.SetCallSecondStageSelection
    @FellowshipCallId uniqueidentifier,
    @ApplicationId uniqueidentifier,
    @IsSelected bit,
    @ActorIdentity nvarchar(255),
    @ActorGroup nvarchar(128),
    @ActorEntraObjectId uniqueidentifier
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @ActorEntraObjectId IS NULL OR LEN(LTRIM(RTRIM(@ActorIdentity))) = 0
       OR NOT EXISTS (
           SELECT 1 FROM dbo.FellowshipCallGroupGrant
           WHERE FellowshipCallId = @FellowshipCallId
             AND GroupName = @ActorGroup AND IsActive = 1 AND AccessRole = ''ADMINISTER''
       ) THROW 55102, ''The call is unavailable.'', 1;
    IF NOT EXISTS (
        SELECT 1 FROM dbo.Application
        WHERE FellowshipCallId = @FellowshipCallId AND ApplicationId = @ApplicationId
    ) THROW 55103, ''The applicant is unavailable.'', 1;
    BEGIN TRANSACTION;
    UPDATE dbo.CallSecondStageSelection WITH (UPDLOCK, SERIALIZABLE)
    SET IsSelected = @IsSelected, ModifiedByIdentity = @ActorIdentity,
        RecordedAtUtc = SYSUTCDATETIME()
    WHERE FellowshipCallId = @FellowshipCallId AND ApplicationId = @ApplicationId;
    IF @@ROWCOUNT = 0
        INSERT dbo.CallSecondStageSelection
            (FellowshipCallId, ApplicationId, IsSelected, ModifiedByIdentity)
        VALUES (@FellowshipCallId, @ApplicationId, @IsSelected, @ActorIdentity);
    COMMIT;
    SELECT @IsSelected;
END;
');

GRANT EXECUTE ON dbo.GetCallSecondStageSelections TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.SetCallSecondStageSelection TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.CallSecondStageSelection TO EHFApplicationRuntime;
