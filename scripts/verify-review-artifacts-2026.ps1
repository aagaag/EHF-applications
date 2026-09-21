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
    rows = connection.cursor().execute("""
        SELECT p.Category, COUNT(DISTINCT p.ApplicationId),
               COUNT(DISTINCT p.ArtifactDocumentVersionId)
        FROM dbo.InternalReviewArtifactProvenance AS p
        JOIN dbo.DocumentVersion AS v
          ON v.DocumentVersionId=p.ArtifactDocumentVersionId
        JOIN dbo.Document AS d ON d.DocumentId=v.DocumentId
        JOIN dbo.DocumentSlot AS s ON s.DocumentSlotId=d.DocumentSlotId
        JOIN dbo.StoredObject AS o ON o.StoredObjectId=v.StoredObjectId
        WHERE s.ActiveDocumentVersionId=v.DocumentVersionId
          AND s.ApplicantVisible=0
          AND v.Classification='INTERNAL_ADMINISTRATIVE'
          AND o.ScanResult='CLEAN'
        GROUP BY p.Category
        ORDER BY p.Category
    """).fetchall()
    counts = {row[0]: (row[1], row[2]) for row in rows}
    expected = {
        'APPLICATION': (30, 30),
        'CURRICULUM': (23, 23),
        'PUBLICATIONS': (26, 26),
    }
    for category in ('APPLICATION', 'CURRICULUM', 'PUBLICATIONS'):
        applications, artifacts = counts.get(category, (0, 0))
        print(f'{category}: {applications} applications, {artifacts} active artifacts')
    if counts != expected:
        raise RuntimeError('review-artifact category verification contract failed')
finally:
    connection.close()
PY
'@
$EncodedScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RemoteScript.Replace("`r`n", "`n")))
& ssh.exe -o BatchMode=yes $Target "printf %s '$EncodedScript' | /usr/bin/base64 --decode | sudo -n /bin/sh -s -- '$SqlAdminCredentialPath'"
if ($LASTEXITCODE -ne 0) { throw 'Review-artifact verification failed.' }
