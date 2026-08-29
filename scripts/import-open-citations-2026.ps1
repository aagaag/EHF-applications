[CmdletBinding(DefaultParameterSetName = 'PlanOnly')]
param(
    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string] $ManifestPath,

    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string] $SnapshotPath,

    [ValidatePattern('^/[A-Za-z0-9._/-]+$')]
    [string] $SqlAdminCredentialPath = '',

    [Parameter(ParameterSetName = 'Apply', Mandatory)]
    [switch] $Apply
)

$ErrorActionPreference = 'Stop'
$Target = 'isab-db01-hestia'
$TransferId = [Guid]::NewGuid().ToString('N')
$RemoteTransfer = "/home/aag/.ehf-open-citation-transfer/$TransferId"
$RemoteManifest = "$RemoteTransfer/manifest.json"
$RemoteSnapshot = "$RemoteTransfer/open-citations.csv"
$ApplyFlag = if ($Apply) { '--apply' } else { '--plan-only' }
$ManifestFullPath = [IO.Path]::GetFullPath($ManifestPath)
$SnapshotFullPath = [IO.Path]::GetFullPath($SnapshotPath)
$RepositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($ManifestFullPath.StartsWith($RepositoryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The publication manifest must remain outside the repository.'
}
if ($SnapshotFullPath.StartsWith($RepositoryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The open citation snapshot must remain outside the repository.'
}
if ($Apply -and -not $SqlAdminCredentialPath) {
    throw 'Apply requires the protected SQL administrator credential path; do not provide a credential value.'
}

try {
    & ssh.exe -o BatchMode=yes $Target "umask 077; mkdir -p -- '/home/aag/.ehf-open-citation-transfer'; chmod 700 -- '/home/aag/.ehf-open-citation-transfer'; mkdir -- '$RemoteTransfer'; chmod 700 -- '$RemoteTransfer'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the protected open citation transfer directory.' }
    & scp.exe -q $ManifestFullPath "${Target}:$RemoteManifest"
    if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the publication manifest.' }
    & scp.exe -q $SnapshotFullPath "${Target}:$RemoteSnapshot"
    if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the open citation snapshot.' }
    & ssh.exe -o BatchMode=yes $Target "chmod 600 -- '$RemoteManifest' '$RemoteSnapshot'; test `"`$(/usr/bin/stat -c '%U:%G:%a' '$RemoteManifest')`" = 'aag:aag:600'; test `"`$(/usr/bin/stat -c '%U:%G:%a' '$RemoteSnapshot')`" = 'aag:aag:600'"
    if ($LASTEXITCODE -ne 0) { throw 'The open citation transfer has unsafe permissions.' }

    $RemoteScript = @'
set -eu
manifest=$1
snapshot=$2
apply_flag=$3
sql_admin_path=$4
/usr/bin/install -d -o root -g root -m 0700 /root/ehf-import
stage=$( /usr/bin/mktemp -d /root/ehf-import/open-citations-2026.XXXXXX )
cleanup() {
  /usr/bin/rm -f -- "$manifest" "$snapshot"
  case "$stage" in /root/ehf-import/open-citations-2026.*) /usr/bin/rm -rf -- "$stage" ;; *) exit 2 ;; esac
}
trap cleanup EXIT
/usr/bin/chmod 0700 /root/ehf-import "$stage"
/usr/bin/install -m 0600 -o root -g root "$manifest" "$stage/manifest.json"
/usr/bin/install -m 0600 -o root -g root "$snapshot" "$stage/open-citations.csv"
release=$( /usr/bin/readlink -f /opt/ehf/current )
python="$release/venv/bin/python"
cd "$release"
set -a
. /etc/ehf/ehf.env
set +a
if [ "$apply_flag" = '--apply' ]; then
  "$python" -m app.importer.run_open_citations --manifest "$stage/manifest.json" --snapshot "$stage/open-citations.csv" --apply --sql-admin-credential-file "$sql_admin_path"
else
  "$python" -m app.importer.run_open_citations --manifest "$stage/manifest.json" --snapshot "$stage/open-citations.csv" --plan-only
fi
'@
    $EncodedScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RemoteScript.Replace("`r`n", "`n")))
    & ssh.exe -o BatchMode=yes $Target "printf %s '$EncodedScript' | /usr/bin/base64 --decode | sudo -n /bin/sh -s -- '$RemoteManifest' '$RemoteSnapshot' '$ApplyFlag' '$SqlAdminCredentialPath'"
    if ($LASTEXITCODE -ne 0) { throw 'The root-mediated open citation import operation failed.' }
}
finally {
    & ssh.exe -o BatchMode=yes $Target "rm -rf -- '$RemoteTransfer'" 2>$null | Out-Null
}
