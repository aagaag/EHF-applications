# EHF SQL permissions

The production runtime uses only the SQL login and database user `ehf_app`.
Migration 005 creates the database user without a login, the dedicated
`EHFApplicationRuntime` role, and a no-personal-data `dbo.RuntimeHealth`
procedure. `infra/setup-sql-login.sh` is the only provisioning entry point.
It delegates dynamic principal operations to `infra/sql-principal.py`, whose
fixed commands accept only the expected EHF names or a randomized test shape;
it has no arbitrary-SQL mode.

Run setup on ISAB01 as root with the protected SQL administrator credential
path supplied out of band:

```bash
EHF_SQL_ADMIN_PASSWORD_FILE=/protected/root-only/sql-admin-password \
EHF_SQL_PRINCIPAL_PYTHON=/opt/ehf/venv/bin/python \
  bash infra/setup-sql-login.sh
```

`/opt/ehf/venv/bin/python` must be Python 3.12 with the pinned
`pyodbc==5.3.0` dependency. Task 7 provisions that runtime; setup fails before
SQL changes when it is unavailable. The helper reads only root-owned regular
credential files itself, uses ODBC parameter binding, and emits fixed errors.

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

The login has no user in `master` and no user, role membership, or database
ownership outside `EHFApplications`; setup refuses any existing mapping or
ownership before it changes SQL or files. A caller can change its own SQL
password when it knows its current password, which is inherent SQL Server
behavior and does not grant `ALTER ANY LOGIN`; the runtime test uses a wrong
`OLD_PASSWORD` attempt and confirms that server-level elevation remains denied.

The procedure grants are not application authorization. A later application
layer task must supply authenticated identity, actor identity, and application
scope before it calls status-changing procedures.

For a non-production verification run on ISAB01, supply the same protected
administrator credential path and execute:

```bash
EHF_SQL_ADMIN_PASSWORD_FILE=/protected/root-only/sql-admin-password \
EHF_SQL_PRINCIPAL_PYTHON=/temporary/pyodbc-venv/bin/python \
  bash infra/test-sql-login.sh
```

The verifier generates one random `EHFApplications_Test_sqlperm_…` database
and matching `ehf_app_test_…` login/user. It refuses any other name, suppresses
credential-bearing command output, and its exit trap removes only the database
and principals it created in that run. It also creates a second isolated
database, proves the real temporary login cannot read it, exercises
`SetApplicationStatus` against synthetic-only records, and verifies no test
database or login remains before printing `PASS`.
