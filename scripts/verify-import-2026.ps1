[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidatePattern('^[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}$')] [string] $CallId,
    [ValidatePattern('^/[A-Za-z0-9._/-]+$')] [string] $SqlAdminCredentialPath = '/root/.config/finances2/sql-sa'
)

$ErrorActionPreference = 'Stop'
$Target = 'isab-db01-hestia'
$EncodedCallId = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($CallId))
$RemoteScript = @'
set -eu
call_id=$(printf '%s' "$1" | /usr/bin/base64 --decode)
release=$( /usr/bin/readlink -f /opt/ehf/current )
set -a
. /etc/ehf/ehf.env
set +a
"$release/venv/bin/python" - "$call_id" "$2" <<'PY'
import hashlib
import os
import pwd
import stat
import sys
from pathlib import Path
import pyodbc

call_id = sys.argv[1]
credential_path = Path(sys.argv[2])
if credential_path.is_symlink() or not credential_path.is_file() or credential_path.stat().st_mode & 0o077:
    raise RuntimeError('unsafe SQL administrator credential path')
password = credential_path.read_text(encoding='utf-8').strip()
connection = pyodbc.connect(
    'DRIVER={ODBC Driver 18 for SQL Server};SERVER=' + os.environ.get('EHF_SQL_SERVER', 'tcp:127.0.0.1,1433') +
    ';DATABASE=' + os.environ.get('EHF_SQL_DATABASE', 'EHFApplications') + ';UID=sa;PWD={' + password.replace('}', '}}') +
    '};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=15;'
)
try:
    cursor = connection.cursor()
    completed = cursor.execute("SELECT TOP (1) ImportRunId FROM dbo.ImportRun WHERE FellowshipCallId = ? AND RunStatus = 'COMPLETED' ORDER BY CompletedAtUtc DESC", call_id).fetchone()
    if completed is None:
        raise RuntimeError('no completed import run')
    run_id = completed[0]
    run = cursor.execute("SELECT COUNT(*) FROM dbo.ImportRun WHERE FellowshipCallId = ? AND RunStatus = 'COMPLETED'", call_id).fetchone()[0]
    applications = cursor.execute("SELECT COUNT(DISTINCT ApplicationId) FROM dbo.ImportRow WHERE ImportRunId = ? AND MatchStatus = 'MATCHED'", run_id).fetchone()[0]
    application_occurrences = cursor.execute("SELECT COUNT(*) FROM dbo.SourceOccurrence WHERE ImportRunId = ?", run_id).fetchone()[0]
    call_occurrences = cursor.execute("SELECT COUNT(*) FROM dbo.CallSourceOccurrence WHERE ImportRunId = ?", run_id).fetchone()[0]
    rejected_nonempty = cursor.execute("SELECT COUNT(*) FROM dbo.SourceOccurrence WHERE ImportRunId = ? AND ImportDisposition = 'REJECTED' AND SourceByteSize > 0", run_id).fetchone()[0]
    rejected_empty = cursor.execute("SELECT COUNT(*) FROM dbo.SourceOccurrence WHERE ImportRunId = ? AND ImportDisposition = 'REJECTED' AND SourceByteSize = 0", run_id).fetchone()[0]
    unreviewed = cursor.execute("SELECT COUNT(DISTINCT v.DocumentVersionId) FROM dbo.DocumentVersion AS v JOIN dbo.SourceOccurrence AS o ON o.DocumentVersionId = v.DocumentVersionId WHERE o.ImportRunId = ? AND v.Classification = 'UNREVIEWED'", run_id).fetchone()[0]
    applicant_visible = cursor.execute("SELECT COUNT(*) FROM dbo.vw_ApplicantVisibleDocumentVersion AS d JOIN dbo.Application AS a ON a.ApplicationId = d.ApplicationId WHERE a.FellowshipCallId = ?", call_id).fetchone()[0]
    recommendations = cursor.execute("SELECT COUNT(*) FROM dbo.Recommendation AS r JOIN dbo.Document AS d ON d.DocumentId = r.DocumentId JOIN dbo.DocumentSlot AS s ON s.DocumentSlotId = d.DocumentSlotId JOIN dbo.Application AS a ON a.ApplicationId = s.ApplicationId WHERE a.FellowshipCallId = ?", call_id).fetchone()[0]
    objects = cursor.execute("SELECT DISTINCT so.ObjectKey, so.CiphertextSha256 FROM dbo.StoredObject AS so JOIN dbo.DocumentVersion AS v ON v.StoredObjectId = so.StoredObjectId JOIN dbo.SourceOccurrence AS o ON o.DocumentVersionId = v.DocumentVersionId WHERE o.ImportRunId = ?", run_id).fetchall()
    root = Path('/var/lib/ehf/documents/o')
    account = pwd.getpwnam('ehf')
    for key, digest in objects:
        path = root / key
        details = path.stat()
        if details.st_uid != account.pw_uid or details.st_gid != account.pw_gid or stat.S_IMODE(details.st_mode) != 0o600:
            raise RuntimeError('unsafe encrypted object ownership')
        if hashlib.sha256(path.read_bytes()).digest() != bytes(digest):
            raise RuntimeError('object hash mismatch')
    print(f'Completed import runs: {run}')
    print(f'Imported applications: {applications}')
    print(f'Accounted source occurrences: {application_occurrences + call_occurrences}')
    print(f'Reviewed internal exclusions: {call_occurrences}')
    print(f'Empty rejected source files: {rejected_empty}')
    print(f'UNREVIEWED document versions: {unreviewed}')
    print(f'Confidential recommendation links: {recommendations}')
    print(f'Applicant-visible documents: {applicant_visible}')
    print(f'Encrypted object hashes verified: {len(objects)}')
    if (run < 1 or applications != 36 or application_occurrences + call_occurrences != 164
            or call_occurrences != 10 or rejected_nonempty != 0 or rejected_empty != 1
            or applicant_visible != 0):
        raise RuntimeError('import verification contract failed')
finally:
    connection.close()
PY
'@
$EncodedScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RemoteScript.Replace("`r`n", "`n")))
& ssh.exe -o BatchMode=yes $Target "printf %s '$EncodedScript' | /usr/bin/base64 --decode | sudo -n /bin/sh -s -- '$EncodedCallId' '$SqlAdminCredentialPath'"
if ($LASTEXITCODE -ne 0) { throw 'ISAB01 import verification failed.' }
