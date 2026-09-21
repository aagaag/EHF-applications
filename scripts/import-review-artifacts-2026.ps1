[CmdletBinding(DefaultParameterSetName = 'PlanOnly')]
param(
    [Parameter(Mandatory)] [string] $ManifestPath,
    [Parameter(Mandatory)] [string] $SourceRoot,
    [ValidatePattern('^/[A-Za-z0-9._/-]+$')] [string] $SqlAdminCredentialPath = '',
    [Parameter(ParameterSetName = 'Apply', Mandatory)] [switch] $Apply
)

$ErrorActionPreference = 'Stop'
$Manifest = [IO.Path]::GetFullPath($ManifestPath)
$Sources = [IO.Path]::GetFullPath($SourceRoot)
$Repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($Manifest.StartsWith($Repository + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The private review-artifact manifest must remain outside the repository.'
}
if (-not $Apply) {
    & 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m app.importer.run_review_artifacts --manifest $Manifest --source-root $Sources --plan-only
    exit $LASTEXITCODE
}
if (-not $SqlAdminCredentialPath) { throw 'Apply requires the protected SQL administrator credential path.' }

$Target = 'ehf-hestia'
$TransferId = [Guid]::NewGuid().ToString('N')
$RemoteDirectory = "/home/aag/.ehf-review-artifacts/$TransferId"
$RemoteManifest = "$RemoteDirectory/manifest.json"
try {
    & ssh.exe -o BatchMode=yes $Target "umask 077; mkdir -p -- '/home/aag/.ehf-review-artifacts'; mkdir -- '$RemoteDirectory'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the protected review-artifact transfer directory.' }
    & scp.exe -q $Manifest "${Target}:$RemoteManifest"
    if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the private review-artifact manifest.' }
    $RemoteScript = @'
set -eu
manifest=$1
sql_admin=$2
release=$( /usr/bin/readlink -f /opt/ehf/current )
cd "$release"
set -a
. /etc/ehf/ehf.env
set +a
/usr/bin/install -d -o root -g root -m 0700 /root/ehf-review-artifacts-empty-source
"$release/venv/bin/python" -m app.importer.run_review_artifacts --manifest "$manifest" --source-root /root/ehf-review-artifacts-empty-source --apply --sql-admin-credential-file "$sql_admin"
'@
    $Encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RemoteScript.Replace("`r`n", "`n")))
    & ssh.exe -o BatchMode=yes $Target "chmod 600 -- '$RemoteManifest'; printf %s '$Encoded' | /usr/bin/base64 --decode | sudo -n /bin/sh -s -- '$RemoteManifest' '$SqlAdminCredentialPath'"
    if ($LASTEXITCODE -ne 0) { throw 'The root-mediated review-artifact import failed.' }
}
finally {
    & ssh.exe -o BatchMode=yes $Target "rm -rf -- '$RemoteDirectory'" 2>$null | Out-Null
}
