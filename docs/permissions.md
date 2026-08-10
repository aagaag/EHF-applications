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
The isolated verifier never reads the SQL administrator credential in the shell:
the helper supplies it only to a fixed SQLCMD invocation for repository-owned
migrations and validators, or to fixed ODBC checks.
The application password is created only once at `/etc/ehf/sql-app-password`
as `root:ehf`, mode `0640`; it is never printed or put in argv. Existing logins
must authenticate from that file before any mapping change. An authenticated,
otherwise exact `UNMAPPED` state converges to the one expected EHF user mapping;
any direct permission, extra role, ownership, external mapping, unexpected
server permission, or effective access to another user database is refused.

The production login is enabled, has `CHECK_POLICY=ON`,
`CHECK_EXPIRATION=OFF`, and defaults to `EHFApplications`. It has no server
role, does not own `EHFApplications`, and has exactly these five explicit
server denials: `VIEW ANY DATABASE`, `VIEW ANY DEFINITION`, `VIEW SERVER
STATE`, `ALTER ANY LOGIN`, and `ALTER ANY SERVER ROLE`. The login has no
direct `CONTROL SERVER` grant or denial: the controlled live probe established
that an explicit `DENY CONTROL SERVER` prevents SQL login authentication with
SQL Server error 18456. Effective `CONTROL SERVER` remains required to be
unavailable, by absence of a grant or server-role membership and by the five
narrower denials, and is checked by the isolated verifier. It has no user in
`master` or another application database. The runtime user has no direct
database grant and belongs only to `EHFApplicationRuntime`.

The role receives `CONNECT` and object-scoped `EXECUTE` only on
`dbo.RuntimeHealth`, `dbo.SetUserPreference`, `dbo.GetUserPreference`,
`dbo.SetApplicationStatus`, `dbo.ValidateApplicationInvitation`,
`dbo.GetInternalApplicationMetrics`, and `dbo.RecordReportExportAudit`. It
receives no table or schema grant and has explicit table DML/read denials.
`SetUserPreference` retains its migration-004 execution principal, so
preference and audit writes remain one transaction despite direct DML being
denied. `RecordReportExportAudit` similarly executes as the dedicated
`EHFReportExportAuditExecutor`, accepts only the two canonical EHF roles and
fixed completed/failed outcomes, and appends only bounded XLSX export facts.
The runtime cannot read or write `dbo.AuditEvent` directly and cannot
impersonate either procedure execution principal.

Validator 005 treats the runtime role's database permissions as an exact set:
every grant and denial must have its intended class, major/minor scope, name,
and state. `GRANT_WITH_GRANT_OPTION`, a missing metadata/schema/user denial, or
any additional permission row fails validation. The role is owned by `dbo`,
contains exactly the `ehf_app` member, is not nested in another role, and owns
no schema, object, or principal.

Production user mapping revalidates the complete unmapped-user shape inside an
explicit `XACT_ABORT` transaction. SQL Server does not permit a `SQL_USER`
created `WITHOUT LOGIN` to be remapped with `ALTER USER ... WITH LOGIN` (error
33016). Only after every precheck, fixed dynamic SQL safely quotes the validated
identifiers and atomically drops the user's runtime-role membership, drops the
user, recreates the same user name for the expected login, revokes the direct
`CONNECT` that SQL Server adds during `CREATE USER ... FOR LOGIN`, and restores
the runtime-role membership. Any failure rolls back the complete transition,
and the mapped postcondition is rechecked before commit. Both checks include
the enabled SQL login, default database, password-policy flags, five-denial
direct server-permission shape, absence of server roles and database ownership,
and the complete dbo-owned sole-member runtime-role topology. The production
batch grants no direct permission; database `CONNECT` remains available only
through `EHFApplicationRuntime`. The earlier lifecycle and effective
cross-database checks remain additional preconditions.

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
resources. Every run token is suffix-bound to the randomized 24-hex resource
suffix. Cleanup deletes a current-run login only when both current-run database
markers match that token and the login has the exact temporary-login shape; it
deletes each database only when its own marker matches. It neither requires nor
uses a credential during cleanup, so an interrupted run remains deterministically
auditable. The verifier seeds a separate test-shaped peer/login with different
suffix-bound markers, proves current-run cleanup preserves it, then removes it
only with its own evidence. Cleanup is explicit and globally verified before
`PASS`; the EXIT trap remains as failure safety.

The peer-database isolation probe uses a fixed helper command with a
suffix-matched randomized peer database and login plus the protected test
credential. A denial is accepted only when the pyodbc diagnostic has exactly
SQLSTATE 42000, names the exact requested database in SQL Server's
“cannot open database … requested by the login” sentence, and carries native
code (4060). Successful connections, malformed diagnostics, wrong database
names, and authentication, TLS, timeout, driver, query, or other ODBC errors
fail closed. The same classifier and database binding protect production
ordinary-user-database isolation checks.

For setup convergence, an UNMAPPED login first completes credential-bearing
effective cross-database verification, then maps through the fail-closed helper,
and only afterward authenticates directly to EHFApplications. READY may
authenticate directly. A newly created ABSENT login likewise reaches UNMAPPED,
is verified and mapped, and authenticates to the expected database only after
mapping.
