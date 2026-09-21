[CmdletBinding()]
param(
    [ValidatePattern('^/[A-Za-z0-9._/-]+$')]
    [string] $SqlAdminCredentialPath = '/etc/ehf/sql-admin-password'
)

$ErrorActionPreference = 'Stop'
$Target = 'ehf-hestia'
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
        or resolved != Path('/etc/ehf/sql-admin-password')):
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
    run = cursor.execute("SELECT TOP (1) ImportRunId FROM dbo.ImportRun WHERE FellowshipCallId=? AND ImporterVersion='2026.7-source-cutoff' AND RunStatus='COMPLETED' ORDER BY CompletedAtUtc DESC", call_id).fetchone()
    if run is None:
        raise RuntimeError('no completed open citation import run')
    latest = cursor.execute("""
    SELECT CONVERT(varchar(36), observation.ApplicationPublicationId),
           observation.SourceCode, observation.CitationStatus,
           observation.CitationCount, observation.ObservedAtUtc, observation.EvidenceJson,
           JSON_VALUE(observation.EvidenceJson, '$.journal_openalex_id'),
           JSON_VALUE(observation.EvidenceJson, '$.journal_source_type'),
           JSON_VALUE(observation.EvidenceJson, '$.journal_two_year_mean_citedness'),
           TRY_CONVERT(decimal(18,6), JSON_VALUE(observation.EvidenceJson, '$.journal_two_year_mean_citedness')),
           publication.PublicationYear,
           JSON_VALUE(observation.EvidenceJson, '$.journal_metric_observed_at_utc')
    FROM dbo.PublicationCitationObservation AS observation
    JOIN dbo.ApplicationPublication AS publication
      ON publication.ApplicationPublicationId = observation.ApplicationPublicationId
    WHERE observation.ImportRunId=?
      AND observation.SourceCode='OPENALEX'
    """, run[0]).fetchall()
    openalex = {row[0]: row for row in latest if row[1] == 'OPENALEX'}
    observation_rows = len(latest)
    openalex_rows = len(openalex)
    source_rows = cursor.execute("SELECT COUNT(*) FROM dbo.ImportRow WHERE ImportRunId=? AND MatchStatus='MATCHED'", run[0]).fetchone()[0]
    invalid = sum(
        row[2] not in {'OBSERVED','NOT_FOUND'}
        or (row[2] == 'OBSERVED' and row[3] is None)
        or (row[2] == 'NOT_FOUND' and row[3] is not None)
        or row[4] is None or row[5] is None
        for row in latest
    )
    journal_source_count = sum(bool(row[6]) for row in latest)
    valid_journal_metric_count = sum(
        row[6] is not None
        and row[7] == 'journal'
        and row[8] is not None
        and row[9] is not None
        and row[9] >= 0
        for row in latest
    )
    journal_na_count = sum(
        row[10] is not None
        and not (
            row[6] is not None
            and row[7] == 'journal'
            and row[8] is not None
            and row[9] is not None
            and row[9] >= 0
        )
        for row in latest
    )
    missing_year_count = sum(row[10] is None for row in latest)
    invalid_or_non_journal_count = sum(
        row[6] is not None
        and (
            row[7] != 'journal'
            or (row[8] is not None and (row[9] is None or row[9] < 0))
        )
        for row in latest
    )
    invalid_journal_evidence = sum(
        row[8] is not None
        and (
            row[6] is None
            or row[7] != 'journal'
            or row[9] is None
            or row[9] < 0
        )
        for row in latest
    )
    latest_journal_observation = max(
        (row[11] or str(row[4]) for row in latest),
        default='N/A',
    )
    print(f'Latest OpenAlex rows: {openalex_rows}')
    print(f'Current-run OpenAlex observations: {observation_rows}')
    print(f'Imported source rows: {source_rows}')
    print(f'OpenAlex observed: {sum(row[2] == "OBSERVED" for row in openalex.values())}')
    print(f'OpenAlex not found: {sum(row[2] == "NOT_FOUND" for row in openalex.values())}')
    print(f'Journal-source publications: {journal_source_count}')
    print(f'Valid OpenAlex 2-year journal citedness: {valid_journal_metric_count}')
    print(f'Journal citedness N/A: {journal_na_count}')
    print(f'Missing publication year: {missing_year_count}')
    print(f'Invalid or non-journal sources: {invalid_or_non_journal_count}')
    print(f'Latest journal observation: {latest_journal_observation}')
    if (source_rows != 932 or observation_rows != 932 or openalex_rows != 932
            or invalid != 0 or invalid_journal_evidence != 0):
        raise RuntimeError('open citation verification contract failed')
finally:
    connection.close()
PY
'@
$EncodedScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RemoteScript.Replace("`r`n", "`n")))
& ssh.exe -o BatchMode=yes $Target "printf %s '$EncodedScript' | /usr/bin/base64 --decode | sudo -n /bin/sh -s -- '$SqlAdminCredentialPath'"
if ($LASTEXITCODE -ne 0) { throw 'the EHF VM open citation verification failed.' }
