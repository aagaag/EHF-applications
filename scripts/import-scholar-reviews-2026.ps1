[CmdletBinding(DefaultParameterSetName = 'PlanOnly')]
param(
    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string] $ManifestPath,

    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string] $ScholarQueuePath,

    [ValidatePattern('^/[A-Za-z0-9._/-]+$')]
    [string] $SqlAdminCredentialPath = '',

    [Parameter(ParameterSetName = 'Apply', Mandatory)]
    [switch] $Apply
)

$ErrorActionPreference = 'Stop'
$Target = 'aag@10.10.20.29'
$TransferId = [Guid]::NewGuid().ToString('N')
$RemoteTransfer = "/home/aag/.ehf-scholar-review-transfer/$TransferId"
$RemoteManifest = "$RemoteTransfer/manifest.json"
$RemoteQueue = "$RemoteTransfer/google-scholar-review.csv"
$ApplyFlag = if ($Apply) { '--apply' } else { '--plan-only' }
$ManifestFullPath = [IO.Path]::GetFullPath($ManifestPath)
$QueueFullPath = [IO.Path]::GetFullPath($ScholarQueuePath)
$RepositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($ManifestFullPath.StartsWith($RepositoryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The publication manifest must remain outside the repository.'
}
if ($QueueFullPath.StartsWith($RepositoryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The reviewed Scholar queue must remain outside the repository.'
}
if ($Apply -and -not $SqlAdminCredentialPath) {
    throw 'Apply requires the protected SQL administrator credential path; do not provide a credential value.'
}

try {
    & ssh.exe -o BatchMode=yes $Target "umask 077; mkdir -p -- '/home/aag/.ehf-scholar-review-transfer'; chmod 700 -- '/home/aag/.ehf-scholar-review-transfer'; mkdir -- '$RemoteTransfer'; chmod 700 -- '$RemoteTransfer'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the protected Scholar review transfer directory.' }
    & scp.exe -q $ManifestFullPath "${Target}:$RemoteManifest"
    if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the publication manifest.' }
    & scp.exe -q $QueueFullPath "${Target}:$RemoteQueue"
    if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the reviewed Scholar queue.' }
    & ssh.exe -o BatchMode=yes $Target "chmod 600 -- '$RemoteManifest' '$RemoteQueue'; test `"`$(/usr/bin/stat -c '%U:%G:%a' '$RemoteManifest')`" = 'aag:aag:600'; test `"`$(/usr/bin/stat -c '%U:%G:%a' '$RemoteQueue')`" = 'aag:aag:600'"
    if ($LASTEXITCODE -ne 0) { throw 'The Scholar review transfer has unsafe permissions.' }

    $RemoteScript = @'
set -eu
manifest=$1
queue=$2
apply_flag=$3
sql_admin_path=$4
/usr/bin/install -d -o root -g root -m 0700 /root/ehf-import
stage=$( /usr/bin/mktemp -d /root/ehf-import/scholar-reviews-2026.XXXXXX )
cleanup() {
  /usr/bin/rm -f -- "$manifest" "$queue"
  case "$stage" in /root/ehf-import/scholar-reviews-2026.*) /usr/bin/rm -rf -- "$stage" ;; *) exit 2 ;; esac
}
trap cleanup EXIT
/usr/bin/chmod 0700 /root/ehf-import "$stage"
/usr/bin/install -m 0600 -o root -g root "$manifest" "$stage/manifest.json"
/usr/bin/install -m 0600 -o root -g root "$queue" "$stage/google-scholar-review.csv"
release=$( /usr/bin/readlink -f /opt/ehf/current )
python="$release/venv/bin/python"
cd "$release"
set -a
. /etc/ehf/ehf.env
set +a
if [ "$apply_flag" = '--apply' ]; then
  "$python" -m app.importer.run_scholar_reviews --manifest "$stage/manifest.json" --scholar-queue "$stage/google-scholar-review.csv" --apply --sql-admin-credential-file "$sql_admin_path"
else
  "$python" -m app.importer.run_scholar_reviews --manifest "$stage/manifest.json" --scholar-queue "$stage/google-scholar-review.csv" --plan-only
fi
'@
    $EncodedScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RemoteScript.Replace("`r`n", "`n")))
    & ssh.exe -o BatchMode=yes $Target "printf %s '$EncodedScript' | /usr/bin/base64 --decode | sudo -n /bin/sh -s -- '$RemoteManifest' '$RemoteQueue' '$ApplyFlag' '$SqlAdminCredentialPath'"
    if ($LASTEXITCODE -ne 0) { throw 'The root-mediated Scholar review import operation failed.' }
}
finally {
    & ssh.exe -o BatchMode=yes $Target "rm -rf -- '$RemoteTransfer'" 2>$null | Out-Null
}
