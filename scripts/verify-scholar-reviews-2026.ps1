[CmdletBinding()]
param(
    [ValidatePattern('^/[A-Za-z0-9._/-]+$')]
    [string] $SqlAdminCredentialPath = '/root/.config/finances2/sql-sa'
)

$ErrorActionPreference = 'Stop'
$Target = 'aag@10.10.20.29'
$RemoteScript = @'
set -eu
/usr/bin/grep -qx 'EHF_INVITATIONS_ENABLED=false' /etc/ehf/ehf.env
/usr/bin/grep -qx 'EHF_PRODUCTION_MAIL_ENABLED=false' /etc/ehf/ehf.env
release=$( /usr/bin/readlink -f /opt/ehf/current )
set -a
. /etc/ehf/ehf.env
set +a
"$release/venv/bin/python" - "$1" <<'PY'
import os
import stat
import sys
from pathlib import Path
import pyodbc

credential_path = Path(sys.argv[1])
resolved = credential_path.resolve()
details = credential_path.stat()
if (credential_path.is_symlink() or not credential_path.is_file()
        or details.st_uid != 0 or stat.S_IMODE(details.st_mode) != 0o600
        or resolved.parent != Path('/root/.config/finances2')):
    raise RuntimeError('unsafe SQL administrator credential path')
password = credential_path.read_text(encoding='utf-8').strip()
connection = pyodbc.connect(
    'DRIVER={ODBC Driver 18 for SQL Server};SERVER=' + os.environ.get('EHF_SQL_SERVER', 'tcp:127.0.0.1,1433') +
    ';DATABASE=' + os.environ.get('EHF_SQL_DATABASE', 'EHFApplications') + ';UID=sa;PWD={' + password.replace('}', '}}') +
    '};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=15;'
)
try:
    cursor = connection.cursor()
    call = cursor.execute("SELECT FellowshipCallId FROM dbo.FellowshipCall WHERE CallCode=N'EHF-2026'").fetchall()
    if len(call) != 1:
        raise RuntimeError('EHF-2026 call is not unique')
    call_id = call[0][0]
    run = cursor.execute("SELECT TOP (1) ImportRunId FROM dbo.ImportRun WHERE FellowshipCallId=? AND ImporterVersion='2026.4-google-scholar-review' AND RunStatus='COMPLETED' ORDER BY CompletedAtUtc DESC", call_id).fetchone()
    if run is None:
        raise RuntimeError('no completed Google Scholar review import run')
    latest_sql = """
    WITH ranked AS
    (
        SELECT observation.CitationStatus, observation.CitationCount,
               observation.ObservedAtUtc, observation.EvidenceJson,
               ROW_NUMBER() OVER
               (
                   PARTITION BY observation.ApplicationPublicationId
                   ORDER BY CASE WHEN observation.ObservedAtUtc IS NULL THEN 1 ELSE 0 END,
                            observation.ObservedAtUtc DESC,
                            observation.RecordedAtUtc DESC,
                            observation.PublicationCitationObservationId DESC
               ) AS row_number
        FROM dbo.PublicationCitationObservation AS observation
        JOIN dbo.ApplicationPublication AS publication_row
          ON publication_row.ApplicationPublicationId=observation.ApplicationPublicationId
        JOIN dbo.Application AS application_row
          ON application_row.ApplicationId=publication_row.ApplicationId
        WHERE application_row.FellowshipCallId=?
          AND observation.SourceCode='GOOGLE_SCHOLAR'
    )
    SELECT CitationStatus,CitationCount,ObservedAtUtc,EvidenceJson FROM ranked WHERE row_number=1
    """
    latest = cursor.execute(latest_sql, call_id).fetchall()
    latest_google_scholar = len(latest)
    pending_manual = sum(row[0] == 'MANUAL_REQUIRED' for row in latest)
    observed = sum(row[0] == 'OBSERVED' for row in latest)
    not_found = sum(row[0] == 'NOT_FOUND' for row in latest)
    invalid_observed = sum(
        (row[0] == 'OBSERVED' and (row[1] is None or row[2] is None))
        or (row[0] == 'NOT_FOUND' and (row[1] is not None or row[2] is None))
        or row[3] is None
        for row in latest
    )
    imported_rows = cursor.execute("SELECT COUNT(*) FROM dbo.ImportRow WHERE ImportRunId=? AND MatchStatus='MATCHED'", run[0]).fetchone()[0]
    print(f'Latest Google Scholar observations: {latest_google_scholar}')
    print(f'Observed citation counts: {observed}')
    print(f'Papers not found in Google Scholar: {not_found}')
    print(f'Pending manual reviews: {pending_manual}')
    if (latest_google_scholar != 841 or imported_rows != 841 or pending_manual != 0
            or observed + not_found != 841 or invalid_observed != 0):
        raise RuntimeError('Google Scholar review verification contract failed')
finally:
    connection.close()
PY
'@
$EncodedScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RemoteScript.Replace("`r`n", "`n")))
& ssh.exe -o BatchMode=yes $Target "printf %s '$EncodedScript' | /usr/bin/base64 --decode | sudo -n /bin/sh -s -- '$SqlAdminCredentialPath'"
if ($LASTEXITCODE -ne 0) { throw 'ISAB01 Google Scholar review verification failed.' }
