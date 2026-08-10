SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.SchemaMigration', N'U') IS NOT NULL
    THROW 51000, 'dbo.SchemaMigration already exists.', 1;

CREATE TABLE dbo.SchemaMigration
(
    MigrationVersion int NOT NULL,
    MigrationName nvarchar(200) NOT NULL,
    ChecksumSha256 binary(32) NOT NULL,
    AppliedAtUtc datetime2(7) NOT NULL
        CONSTRAINT DF_SchemaMigration_AppliedAtUtc DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_SchemaMigration PRIMARY KEY (MigrationVersion),
    CONSTRAINT UQ_SchemaMigration_Name UNIQUE (MigrationName),
    CONSTRAINT CK_SchemaMigration_Version CHECK (MigrationVersion > 0),
    CONSTRAINT CK_SchemaMigration_Name CHECK (LEN(MigrationName) > 0)
);

EXEC(N'
CREATE VIEW dbo.SchemaVersion
AS
    SELECT
        COUNT_BIG(*) AS MigrationCount,
        COALESCE(MAX(MigrationVersion), 0) AS CurrentVersion,
        MAX(AppliedAtUtc) AS LastAppliedAtUtc
    FROM dbo.SchemaMigration;
');

EXEC(N'
CREATE TRIGGER dbo.TR_SchemaMigration_AppendOnly
ON dbo.SchemaMigration
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 51001, ''Schema migration history is append-only.'', 1;
END;
');
