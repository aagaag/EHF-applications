SET NOCOUNT ON;
SET XACT_ABORT ON;

-- Application-layer authenticated identity and authorization must supply actor
-- and application scope; this SQL role only enforces the object boundary.
-- ALTER ANY LOGIN remains denied by the setup script at server scope.

CREATE ROLE EHFApplicationRuntime;
CREATE USER ehf_app WITHOUT LOGIN;
ALTER ROLE EHFApplicationRuntime ADD MEMBER ehf_app;

EXEC(N'
CREATE PROCEDURE dbo.RuntimeHealth
AS
BEGIN
    SET NOCOUNT ON;
    SELECT CAST(1 AS bit) AS IsReady;
END;
');

GRANT CONNECT TO EHFApplicationRuntime;
REVOKE CONNECT FROM ehf_app;
GRANT EXECUTE ON dbo.RuntimeHealth TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.SetUserPreference TO EHFApplicationRuntime;
GRANT EXECUTE ON dbo.SetApplicationStatus TO EHFApplicationRuntime;

DENY VIEW DEFINITION TO EHFApplicationRuntime;
DENY CREATE TABLE, CREATE PROCEDURE, CREATE VIEW,
    ALTER ANY SCHEMA, ALTER ANY USER, ALTER ANY ROLE
    TO EHFApplicationRuntime;
DENY ALTER ON SCHEMA::dbo TO EHFApplicationRuntime;
DENY IMPERSONATE ON USER::EHFPreferenceProcedureExecutor
    TO EHFApplicationRuntime;

DENY SELECT, INSERT, UPDATE, DELETE ON dbo.SchemaMigration TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.FellowshipCall TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.Applicant TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantContact TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.Application TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.EmploymentAffiliation TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.Qualification TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.EligibilityDeclaration TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.Bibliometrics TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ContributionStatement TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.FieldProvenance TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicationSectionVersion TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.AuditEvent TO EHFApplicationRuntime;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.UserPreference TO EHFApplicationRuntime;
