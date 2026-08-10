# EHF SQL permissions

The production runtime uses only the SQL login and database user `ehf_app`.
Migration 005 creates the database user without a login, the dedicated
`EHFApplicationRuntime` role, and a no-personal-data `dbo.RuntimeHealth`
procedure. `infra/setup-sql-login.sh` is the only provisioning entry point:
it maps the migration-created user to the login after validating the exact
existing shape.

Run setup on ISAB01 as root with the protected SQL administrator credential
path supplied out of band:

```bash
EHF_SQL_ADMIN_PASSWORD_FILE=/protected/root-only/sql-admin-password \
  bash infra/setup-sql-login.sh
```

The script creates `/etc/ehf/sql-app-password` only when it does not already
exist. The resulting regular file is exactly `root:ehf`, mode `0640`; it is
never printed or supplied on a command line. A later systemd service must use
`LoadCredential=sql-password:/etc/ehf/sql-app-password`.

The runtime role receives `CONNECT` and `EXECUTE` only on
`dbo.RuntimeHealth`, `dbo.SetUserPreference`, and `dbo.SetApplicationStatus`.
It receives no table or schema grant, no published view in this task, and an
explicit `SELECT`/`INSERT`/`UPDATE`/`DELETE` denial for every EHF table.
`SetUserPreference` keeps its migration-004 execution principal, so its
preference and audit writes remain one transaction even though direct table
DML is denied to the runtime identity.

For a non-production verification run on ISAB01, supply the same protected
administrator credential path and execute:

```bash
EHF_SQL_ADMIN_PASSWORD_FILE=/protected/root-only/sql-admin-password \
  bash infra/test-sql-login.sh
```

The verifier generates one random `EHFApplications_Test_sqlperm_…` database
and matching `ehf_app_test_…` login/user. It refuses any other name, suppresses
credential-bearing command output, and its exit trap removes only the database
and principals it created in that run.
