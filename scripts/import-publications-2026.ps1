[CmdletBinding(DefaultParameterSetName = 'PlanOnly')]
param(
    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string] $ManifestPath,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string] $ScholarQueuePath,

    [ValidatePattern('^/[A-Za-z0-9._/-]+$')]
    [string] $SqlAdminCredentialPath = '',

    [Parameter(ParameterSetName = 'Apply', Mandatory)]
    [switch] $Apply
)

$ErrorActionPreference = 'Stop'
$Target = 'aag@10.10.20.29'
$TransferId = [Guid]::NewGuid().ToString('N')
$RemoteTransfer = "/home/aag/.ehf-publication-transfer/$TransferId"
$RemoteManifest = "$RemoteTransfer/manifest.json"
$RemoteQueue = "$RemoteTransfer/google-scholar-review.csv"
$RemoteExistingQueue = "$RemoteTransfer/existing-google-scholar-review.csv"
$ApplyFlag = if ($Apply) { '--apply' } else { '' }
$ManifestFullPath = [IO.Path]::GetFullPath($ManifestPath)
$QueueFullPath = [IO.Path]::GetFullPath($ScholarQueuePath)
$RepositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($ManifestFullPath.StartsWith($RepositoryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The publication manifest must remain outside the repository.'
}
if ($QueueFullPath.StartsWith($RepositoryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The Google Scholar review queue must remain outside the repository.'
}
if ($Apply -and -not $SqlAdminCredentialPath) {
    throw 'Apply requires the protected SQL administrator credential path; do not provide a credential value.'
}
$QueueParent = Split-Path -Parent $QueueFullPath
if (-not $QueueParent) { throw 'The Google Scholar review queue path needs a parent directory.' }
[IO.Directory]::CreateDirectory($QueueParent) | Out-Null
$LocalQueueTemp = Join-Path $QueueParent ('.' + [IO.Path]::GetFileName($QueueFullPath) + '.' + $TransferId + '.tmp')
$LocalQueueBackup = Join-Path $QueueParent ('.' + [IO.Path]::GetFileName($QueueFullPath) + '.' + $TransferId + '.bak')
$RemoteExistingQueueArg = ''

try {
    & ssh.exe -o BatchMode=yes $Target "umask 077; mkdir -p -- '/home/aag/.ehf-publication-transfer'; chmod 700 -- '/home/aag/.ehf-publication-transfer'; mkdir -- '$RemoteTransfer'; chmod 700 -- '$RemoteTransfer'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the protected ISAB01 publication transfer directory.' }
    & scp.exe -q $ManifestFullPath "${Target}:$RemoteManifest"
    if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the publication manifest to ISAB01.' }
    & ssh.exe -o BatchMode=yes $Target "chmod 600 -- '$RemoteManifest'; test `"`$(/usr/bin/stat -c '%U:%G:%a' '$RemoteManifest')`" = 'aag:aag:600'"
    if ($LASTEXITCODE -ne 0) { throw 'The publication manifest transfer has unsafe permissions.' }
    if (Test-Path -LiteralPath $QueueFullPath -PathType Leaf) {
        & scp.exe -q $QueueFullPath "${Target}:$RemoteExistingQueue"
        if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the existing Google Scholar review queue to ISAB01.' }
        & ssh.exe -o BatchMode=yes $Target "chmod 600 -- '$RemoteExistingQueue'; test `"`$(/usr/bin/stat -c '%U:%G:%a' '$RemoteExistingQueue')`" = 'aag:aag:600'"
        if ($LASTEXITCODE -ne 0) { throw 'The existing Google Scholar review queue transfer has unsafe permissions.' }
        $RemoteExistingQueueArg = $RemoteExistingQueue
    }

    $RemoteScript = @'
set -eu
manifest=$1
queue_out=$2
existing_queue=$3
apply_flag=$4
sql_admin_path=$5
/usr/bin/install -d -o root -g root -m 0700 /root/ehf-import
stage=$( /usr/bin/mktemp -d /root/ehf-import/publications-2026.XXXXXX )
cleanup() {
  /usr/bin/rm -f -- "$manifest"
  case "$stage" in /root/ehf-import/publications-2026.*) /usr/bin/rm -rf -- "$stage" ;; *) exit 2 ;; esac
}
trap cleanup EXIT
/usr/bin/chmod 0700 /root/ehf-import "$stage"
/usr/bin/install -m 0600 -o root -g root "$manifest" "$stage/manifest.json"
if [ -n "$existing_queue" ]; then
  /usr/bin/install -m 0600 -o root -g root "$existing_queue" "$stage/google-scholar-review.csv"
fi
release=$( /usr/bin/readlink -f /opt/ehf/current )
python="$release/venv/bin/python"
cd "$release"
set -a
. /etc/ehf/ehf.env
set +a
if [ "$apply_flag" = '--apply' ]; then
  "$python" -m app.importer.run_publications --manifest "$stage/manifest.json" --scholar-queue "$stage/google-scholar-review.csv" --apply --sql-admin-credential-file "$sql_admin_path"
else
  "$python" -m app.importer.run_publications --manifest "$stage/manifest.json" --scholar-queue "$stage/google-scholar-review.csv" --plan-only
fi
/usr/bin/install -m 0600 -o aag -g aag "$stage/google-scholar-review.csv" "$queue_out"
'@
    $EncodedScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RemoteScript.Replace("`r`n", "`n")))
    & ssh.exe -o BatchMode=yes $Target "printf %s '$EncodedScript' | /usr/bin/base64 --decode | sudo -n /bin/sh -s -- '$RemoteManifest' '$RemoteQueue' '$RemoteExistingQueueArg' '$ApplyFlag' '$SqlAdminCredentialPath'"
    if ($LASTEXITCODE -ne 0) { throw 'The root-mediated ISAB01 publication import operation failed.' }
    & scp.exe -q "${Target}:$RemoteQueue" $LocalQueueTemp
    if ($LASTEXITCODE -ne 0) { throw 'Could not retrieve the manual Google Scholar review queue.' }
    $Rows = @(Import-Csv -LiteralPath $LocalQueueTemp -Encoding utf8)
    $ExpectedHeaders = @('applicant', 'final_work_id', 'doi', 'title', 'year', 'google_scholar_search_url', 'citation_status', 'citation_count', 'result_url', 'observed_at_utc', 'reviewer')
    $ActualHeaders = @($Rows[0].PSObject.Properties.Name)
    if ($Rows.Count -ne 841 -or ($ActualHeaders -join ',') -ne ($ExpectedHeaders -join ',')) {
        throw 'The retrieved Google Scholar review queue has an invalid row count or header.'
    }
    $WorkIds = @($Rows | ForEach-Object { $_.final_work_id })
    if (($WorkIds | Where-Object { [string]::IsNullOrWhiteSpace($_) }).Count -ne 0 -or
        ($WorkIds | Sort-Object -Unique).Count -ne 841) {
        throw 'The retrieved Google Scholar review queue has missing or duplicate final_work_id values.'
    }
    if (Test-Path -LiteralPath $QueueFullPath -PathType Leaf) {
        [IO.File]::Replace($LocalQueueTemp, $QueueFullPath, $LocalQueueBackup)
        Remove-Item -LiteralPath $LocalQueueBackup -Force
    }
    else {
        [IO.File]::Move($LocalQueueTemp, $QueueFullPath)
    }
}
finally {
    if (Test-Path -LiteralPath $LocalQueueTemp -PathType Leaf) {
        Remove-Item -LiteralPath $LocalQueueTemp -Force
    }
    if (Test-Path -LiteralPath $LocalQueueBackup -PathType Leaf) {
        Remove-Item -LiteralPath $LocalQueueBackup -Force
    }
    & ssh.exe -o BatchMode=yes $Target "rm -rf -- '$RemoteTransfer'" 2>$null | Out-Null
}
