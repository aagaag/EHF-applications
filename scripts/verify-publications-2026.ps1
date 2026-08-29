[CmdletBinding()]
param(
    [ValidatePattern('^/[A-Za-z0-9._/-]+$')]
    [string] $SqlAdminCredentialPath = '/root/.config/finances2/sql-sa'
)

$ErrorActionPreference = 'Stop'
$Target = 'isab-db01-hestia'
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
        or details.st_uid != 0
        or stat.S_IMODE(details.st_mode) != 0o600
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
    run = cursor.execute("SELECT TOP (1) ImportRunId FROM dbo.ImportRun WHERE FellowshipCallId=? AND ImporterVersion='2026.4-publications' AND RunStatus='COMPLETED' ORDER BY CompletedAtUtc DESC", call_id).fetchone()
    if run is None:
        raise RuntimeError('no completed publication import run')
    run_id = run[0]
    applications = cursor.execute("SELECT COUNT(DISTINCT ApplicationId) FROM dbo.ImportRow WHERE ImportRunId=? AND MatchStatus='MATCHED'", run_id).fetchone()[0]
    publications = cursor.execute("SELECT COUNT(*) FROM dbo.ApplicationPublication AS p JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=?", call_id).fetchone()[0]
    occurrences = cursor.execute("SELECT COUNT(*) FROM dbo.ApplicationPublicationSourceOccurrence AS o JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=?", call_id).fetchone()[0]
    metadata = cursor.execute("SELECT COUNT(*) FROM dbo.PublicationMetadataObservation AS o JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=?", call_id).fetchone()[0]
    citations = cursor.execute("SELECT COUNT(*) FROM dbo.PublicationCitationObservation AS o JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=? AND o.ImportRunId=?", call_id, run_id).fetchone()[0]
    doi_rows = cursor.execute("SELECT COUNT(*) FROM dbo.ApplicationPublication AS p JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=? AND p.Doi IS NOT NULL", call_id).fetchone()[0]
    google_scholar_manual = cursor.execute("SELECT COUNT(*) FROM dbo.PublicationCitationObservation AS o JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=? AND o.ImportRunId=? AND o.SourceCode='GOOGLE_SCHOLAR' AND o.CitationStatus='MANUAL_REQUIRED' AND o.CitationCount IS NULL", call_id, run_id).fetchone()[0]
    nonnull_initial_counts = cursor.execute("SELECT COUNT(*) FROM dbo.PublicationCitationObservation AS o JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=? AND o.ImportRunId=? AND o.CitationCount IS NOT NULL", call_id, run_id).fetchone()[0]
    citation_topology_count = cursor.execute("SELECT COUNT(*) FROM (SELECT p.ApplicationPublicationId,required.SourceCode FROM dbo.ApplicationPublication AS p JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId CROSS JOIN (VALUES ('GOOGLE_SCHOLAR'),('BIORXIV'),('MEDRXIV')) AS required(SourceCode) LEFT JOIN dbo.PublicationCitationObservation AS o ON o.ApplicationPublicationId=p.ApplicationPublicationId AND o.SourceCode=required.SourceCode AND o.ImportRunId=? WHERE a.FellowshipCallId=? GROUP BY p.ApplicationPublicationId,required.SourceCode HAVING COUNT(o.PublicationCitationObservationId)<>1) AS invalid_topology", run_id, call_id).fetchone()[0]
    preprint_status_error_count = cursor.execute("SELECT COUNT(*) FROM dbo.PublicationCitationObservation AS o JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=? AND o.ImportRunId=? AND ((o.SourceCode='GOOGLE_SCHOLAR' AND o.CitationStatus<>'MANUAL_REQUIRED') OR (o.SourceCode IN ('BIORXIV','MEDRXIV') AND o.CitationStatus NOT IN ('NOT_AVAILABLE_FROM_SOURCE','NOT_FOUND','NOT_APPLICABLE')) OR o.CitationCount IS NOT NULL)", call_id, run_id).fetchone()[0]
    metadata_topology_count = cursor.execute("SELECT COUNT(*) FROM (SELECT p.ApplicationPublicationId FROM dbo.ApplicationPublication AS p JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId LEFT JOIN dbo.PublicationMetadataObservation AS o ON o.ApplicationPublicationId=p.ApplicationPublicationId WHERE a.FellowshipCallId=? GROUP BY p.ApplicationPublicationId HAVING COUNT(o.PublicationMetadataObservationId)<>1 OR MIN(CASE WHEN o.ObservedAtUtc IS NULL THEN 0 ELSE 1 END)=0) AS invalid_metadata", call_id).fetchone()[0]
    source_type_error_count = cursor.execute("SELECT COUNT(*) FROM dbo.ApplicationPublicationSourceOccurrence AS o JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=? AND o.SourceType<>'DOSSIER'", call_id).fetchone()[0]
    biorxiv_unavailable = cursor.execute("SELECT COUNT(*) FROM dbo.PublicationCitationObservation AS o JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=? AND o.ImportRunId=? AND o.SourceCode='BIORXIV' AND o.CitationStatus='NOT_AVAILABLE_FROM_SOURCE'", call_id, run_id).fetchone()[0]
    biorxiv_not_found = cursor.execute("SELECT COUNT(*) FROM dbo.PublicationCitationObservation AS o JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=? AND o.ImportRunId=? AND o.SourceCode='BIORXIV' AND o.CitationStatus='NOT_FOUND'", call_id, run_id).fetchone()[0]
    biorxiv_not_applicable = cursor.execute("SELECT COUNT(*) FROM dbo.PublicationCitationObservation AS o JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=? AND o.ImportRunId=? AND o.SourceCode='BIORXIV' AND o.CitationStatus='NOT_APPLICABLE'", call_id, run_id).fetchone()[0]
    medrxiv_not_found = cursor.execute("SELECT COUNT(*) FROM dbo.PublicationCitationObservation AS o JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=? AND o.ImportRunId=? AND o.SourceCode='MEDRXIV' AND o.CitationStatus='NOT_FOUND'", call_id, run_id).fetchone()[0]
    medrxiv_not_applicable = cursor.execute("SELECT COUNT(*) FROM dbo.PublicationCitationObservation AS o JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=? AND o.ImportRunId=? AND o.SourceCode='MEDRXIV' AND o.CitationStatus='NOT_APPLICABLE'", call_id, run_id).fetchone()[0]
    duplicate_doi_count = cursor.execute("SELECT COUNT(*) FROM (SELECT p.ApplicationId,p.Doi FROM dbo.ApplicationPublication AS p JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.FellowshipCallId=? AND p.Doi IS NOT NULL GROUP BY p.ApplicationId,p.Doi HAVING COUNT(*)>1) AS duplicate_rows", call_id).fetchone()[0]
    orphan_count = cursor.execute("SELECT (SELECT COUNT(*) FROM dbo.ApplicationPublication AS p LEFT JOIN dbo.Application AS a ON a.ApplicationId=p.ApplicationId WHERE a.ApplicationId IS NULL) + (SELECT COUNT(*) FROM dbo.ApplicationPublicationSourceOccurrence AS o LEFT JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId WHERE p.ApplicationPublicationId IS NULL) + (SELECT COUNT(*) FROM dbo.PublicationMetadataObservation AS o LEFT JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId WHERE p.ApplicationPublicationId IS NULL) + (SELECT COUNT(*) FROM dbo.PublicationCitationObservation AS o LEFT JOIN dbo.ApplicationPublication AS p ON p.ApplicationPublicationId=o.ApplicationPublicationId WHERE p.ApplicationPublicationId IS NULL)").fetchone()[0]
    conflicts = cursor.execute("SELECT COUNT(*) FROM dbo.ImportException WHERE ImportRunId=? AND ExceptionCode LIKE 'PUBLICATION_CONFLICT_%'", run_id).fetchone()[0]
    print(f'Imported applications: {applications}')
    print(f'Application publications: {publications}')
    print(f'Publication source occurrences: {occurrences}')
    print(f'Publication metadata observations: {metadata}')
    print(f'Citation-source observations: {citations}')
    print(f'DOI-bearing publications: {doi_rows}')
    print(f'Google Scholar manual-review rows: {google_scholar_manual}')
    print(f'Publication field conflicts: {conflicts}')
    if (applications != 36 or publications != 841 or occurrences != 883 or metadata != 841
            or citations != 2523 or doi_rows != 519 or google_scholar_manual != 841
            or nonnull_initial_counts != 0 or citation_topology_count != 0
            or preprint_status_error_count != 0 or metadata_topology_count != 0
            or source_type_error_count != 0 or biorxiv_unavailable != 5
            or biorxiv_not_found != 350 or biorxiv_not_applicable != 486
            or medrxiv_not_found != 350 or medrxiv_not_applicable != 491
            or orphan_count != 0 or duplicate_doi_count != 0):
        raise RuntimeError('publication import verification contract failed')
finally:
    connection.close()
PY
'@
$EncodedScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RemoteScript.Replace("`r`n", "`n")))
& ssh.exe -o BatchMode=yes $Target "printf %s '$EncodedScript' | /usr/bin/base64 --decode | sudo -n /bin/sh -s -- '$SqlAdminCredentialPath'"
if ($LASTEXITCODE -ne 0) { throw 'ISAB01 publication import verification failed.' }
