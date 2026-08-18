SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'dbo.SchemaMigration', N'U') IS NULL
    THROW 51100, 'SchemaMigration is missing.', 1;
IF OBJECT_ID(N'dbo.SchemaVersion', N'V') IS NULL
    THROW 51101, 'SchemaVersion is missing.', 1;
IF OBJECT_ID(N'dbo.TR_SchemaMigration_AppendOnly', N'TR') IS NULL
    THROW 51102, 'SchemaMigration append-only guard is missing.', 1;

IF (SELECT COUNT_BIG(*) FROM dbo.SchemaMigration) <> 20
    THROW 51103, 'Exactly twenty migrations must be recorded.', 1;
IF EXISTS
(
    SELECT 1
    FROM dbo.SchemaMigration
    WHERE DATALENGTH(ChecksumSha256) <> 32
       OR AppliedAtUtc > SYSUTCDATETIME()
)
    THROW 51104, 'Migration metadata is invalid.', 1;

IF NOT EXISTS
(
    SELECT 1
    FROM dbo.SchemaVersion
WHERE MigrationCount = 20 AND CurrentVersion = 20
)
    THROW 51105, 'SchemaVersion does not report version 20.', 1;

IF EXISTS
(
    SELECT 1
    FROM sys.tables AS table_row
    WHERE table_row.schema_id = SCHEMA_ID(N'dbo')
      AND table_row.is_ms_shipped = 0
      AND NOT EXISTS
      (
          SELECT 1
          FROM sys.key_constraints AS key_row
          WHERE key_row.parent_object_id = table_row.object_id
            AND key_row.type = 'PK'
      )
)
    THROW 51106, 'Every dbo table must have a primary key.', 1;

IF EXISTS
(
    SELECT 1
    FROM sys.tables AS table_row
    WHERE table_row.schema_id = SCHEMA_ID(N'dbo')
      AND table_row.is_ms_shipped = 0
      AND NOT EXISTS
      (
          SELECT 1
          FROM sys.columns AS column_row
          JOIN sys.types AS type_row
            ON type_row.user_type_id = column_row.user_type_id
          WHERE column_row.object_id = table_row.object_id
            AND column_row.name LIKE '%AtUtc'
            AND type_row.name = 'datetime2'
      )
)
    THROW 51107, 'Every dbo table must have a UTC datetime2 timestamp.', 1;

PRINT 'PASS 001 database contract';
