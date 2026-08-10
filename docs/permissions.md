# EHF SQL permissions

The production runtime uses only the SQL login and database user `ehf_app`.
Migration 005 creates the database user without a login, the dedicated
`EHFApplicationRuntime` role, and the no-personal-data `dbo.RuntimeHealth`
procedure. `infra/setup-sql-login.sh` is the only provisioning entry point.
Its fixed-purpose helper has no arbitrary-SQL mode, accepts only the exact EHF
names or randomized test shapes, uses ODBC parameters, and emits fixed errors.

In production, setup must run from the Task 7 release layout. The only allowed
logical link is `/opt/ehf/current`, resolved to `/opt/ehf/r/<40-hex-commit>`.
The helper and Python runtime must resolve respectively to
`infra/sql-principal.py` and `venv/bin/python` below that release, be
root-owned regular files, and have no group/world-writable parent. The runtime
is Python 3.12 with pinned `pyodbc==5.3.0`; Task 7 installs it.

```bash
EHF_SQL_ADMIN_PASSWORD_FILE=/protected/root-only/sql-admin-password \
  bash /opt/ehf/current/infra/setup-sql-login.sh
```

The helper opens each credential once with `O_NOFOLLOW|O_CLOEXEC`, validates the
opened descriptor and its root-owned, non-writable parent path, then reads it.
The application password is created only once at `/etc/ehf/sql-app-password`
as `root:ehf`, mode `0640`; it is never printed or put in argv. Existing logins
must authenticate from that file before any mapping change. An authenticated,
otherwise exact `UNMAPPED` state converges to the one expected EHF user mapping;
any direct permission, extra role, ownership, external mapping, unexpected
server permission, or effective access to another user database is refused.

The production login has no server role, does not own `EHFApplications`, and
has exactly these explicit server denials: `VIEW ANY DATABASE`, `VIEW ANY
DEFINITION`, `VIEW SERVER STATE`, `ALTER ANY LOGIN`, `ALTER ANY SERVER ROLE`,
and `CONTROL SERVER`. It has no user in `master` or another application
database. The runtime user has no direct database grant and belongs only to
`EHFApplicationRuntime`.

The role receives `CONNECT` and `EXECUTE` only on `dbo.RuntimeHealth`,
`dbo.SetUserPreference`, and `dbo.SetApplicationStatus`. It receives no table
or schema grant and has explicit table DML/read denials. `SetUserPreference`
retains its migration-004 execution principal, so preference and audit writes
remain one transaction despite direct DML being denied.

SQL Server permits a login that knows its old password to rotate its own
password; this is not `ALTER ANY LOGIN` and is not treated as an elevation
failure. If that happens, the protected file no longer authenticates and setup
refuses to take over the login. Recovery is an approved root/SQL-admin incident:
replace the protected credential with a generated safe value, reset only the
exact `ehf_app` login to that value using the controlled admin procedure, then
rerun setup and exact-state inspection. The lifecycle helper deliberately does
not rotate an existing production login.

Application-layer authenticated identity, authorization, actor identity, and
application scope must be supplied by a later application task before any
status-changing call. SQL object permissions are not application authorization.

For an isolated live verification, use an explicit test-only runtime override:

```bash
EHF_SQL_TEST_MODE=1 \
EHF_SQL_ADMIN_PASSWORD_FILE=/protected/root-only/sql-admin-password \
EHF_SQL_PRINCIPAL_PYTHON=/temporary/pyodbc-venv/bin/python \
  bash /temporary/release/infra/test-sql-login.sh
```

The verifier creates only randomized `EHFApplications_Test_sqlperm_…`
resources. Each disposable database carries an opaque `EHF.Task4RunToken`
extended-property marker; a disposable login must authenticate with its
run-specific credential and have its exact expected shape before deletion. It
also seeds a separate test-shaped peer/login, proves current-run cleanup
preserves it, then removes it only with its own token and credential. Cleanup
is explicit and verified before `PASS`; the EXIT trap remains as failure safety.
