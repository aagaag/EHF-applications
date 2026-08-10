SET NOCOUNT ON;
SET XACT_ABORT OFF;

IF OBJECT_ID(N'dbo.RecordReportExportAudit', N'P') IS NULL
    THROW 51920, 'The report-export audit procedure is missing.', 1;
IF DATABASE_PRINCIPAL_ID(N'EHFReportExportAuditExecutor') IS NULL
    THROW 51921, 'The report-export execution principal is missing.', 1;

BEGIN TRY
    EXEC dbo.GetInternalApplicationMetrics @ActorGroup=N'EHF-Administrators';
    EXEC dbo.GetInternalApplicationMetrics @ActorGroup=N'EHF-Trustees';
END TRY
BEGIN CATCH
    THROW 51928, 'The canonical EHF groups cannot read the internal metrics projection.', 1;
END CATCH;

DECLARE @LegacyGroupRejected bit = 0;
BEGIN TRY
    EXEC dbo.GetInternalApplicationMetrics @ActorGroup=N'EHF-Applications-Administrators';
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() <> 51725 THROW;
    SET @LegacyGroupRejected = 1;
END CATCH;
IF @LegacyGroupRejected = 0
    THROW 51929, 'A legacy EHF group name remains authorized by the metrics procedure.', 1;

IF NOT EXISTS
(
    SELECT 1
    FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND class = 1
      AND major_id = OBJECT_ID(N'dbo.RecordReportExportAudit', N'P')
      AND permission_name = N'EXECUTE'
      AND state_desc = N'GRANT'
)
    THROW 51922, 'The runtime report-audit execution grant is missing.', 1;
IF EXISTS
(
    SELECT 1
    FROM sys.database_permissions
    WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND class = 1
      AND major_id = OBJECT_ID(N'dbo.AuditEvent', N'U')
      AND permission_name IN (N'SELECT', N'INSERT', N'UPDATE', N'DELETE')
      AND state_desc LIKE N'GRANT%'
)
    THROW 51923, 'The runtime role has direct audit-table access.', 1;

DECLARE @Rejected bit = 0;
BEGIN TRY
    EXEC dbo.RecordReportExportAudit
        @ActorIdentity=N'validator', @ActorGroup=N'wrong-group',
        @RowCount=1, @Outcome=N'COMPLETED', @FailureStage=NULL;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() <> 51901 THROW;
    SET @Rejected = 1;
END CATCH;
IF @Rejected = 0 THROW 51924, 'An invalid report actor group was accepted.', 1;

SET @Rejected = 0;
BEGIN TRY
    EXEC dbo.RecordReportExportAudit
        @ActorIdentity=N'validator', @ActorGroup=N'EHF-Trustees',
        @RowCount=1, @Outcome=N'UNKNOWN', @FailureStage=NULL;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() <> 51903 THROW;
    SET @Rejected = 1;
END CATCH;
IF @Rejected = 0 THROW 51925, 'An invalid report outcome was accepted.', 1;

BEGIN TRANSACTION;
DECLARE @BeforeCount bigint = (SELECT COUNT_BIG(*) FROM dbo.AuditEvent);
EXEC dbo.RecordReportExportAudit
    @ActorIdentity=N'validator', @ActorGroup=N'EHF-Administrators',
    @RowCount=36, @Outcome=N'COMPLETED', @FailureStage=NULL;
IF (SELECT COUNT_BIG(*) FROM dbo.AuditEvent) <> @BeforeCount + 1
    THROW 51926, 'The completed report export did not append one audit event.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM dbo.AuditEvent
    WHERE EventType = 'REPORT_EXPORT_COMPLETED'
      AND ActorIdentity = N'validator'
      AND EntityType = 'ReportExport'
      AND JSON_VALUE(PayloadJson, '$.actorGroup') = N'EHF-Administrators'
      AND TRY_CONVERT(int, JSON_VALUE(PayloadJson, '$.rowCount')) = 36
      AND JSON_VALUE(PayloadJson, '$.format') = N'XLSX'
      AND JSON_VALUE(PayloadJson, '$.outcome') = N'COMPLETED'
)
    THROW 51927, 'The completed report export audit payload is invalid.', 1;
ROLLBACK TRANSACTION;

PRINT 'PASS 010 report export audit';
