param(
    [Parameter(Mandatory = $true)] [string] $ManifestPath,
    [Parameter(Mandatory = $true)] [string] $OutputPath,
    [string] $Target = 'isab-db01-hestia'
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Manifest = (Resolve-Path -LiteralPath $ManifestPath).Path
$Output = [IO.Path]::GetFullPath($OutputPath)

function Assert-OutsideRepository([string] $Path) {
    $fullPath = [IO.Path]::GetFullPath($Path)
    $repositoryPrefix = $RepositoryRoot.TrimEnd('\') + '\'
    if ($fullPath.Equals($RepositoryRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $fullPath.StartsWith($repositoryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The publication manifest and citation snapshot must remain outside the repository.'
    }
}

Assert-OutsideRepository $Manifest
Assert-OutsideRepository $Output
$OutputDirectory = Split-Path -Parent $Output
if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}

$TransferId = [Guid]::NewGuid().ToString('N')
$RemoteTransfer = "/home/aag/.ehf-open-citation-collect/$TransferId"
$RemoteManifest = "$RemoteTransfer/manifest.json"
$RemoteSnapshot = "$RemoteTransfer/open-citations.csv"
$TemporaryOutput = "$Output.part-$PID"

try {
    & ssh.exe -o BatchMode=yes $Target "umask 077; mkdir -p -- '/home/aag/.ehf-open-citation-collect'; chmod 700 -- '/home/aag/.ehf-open-citation-collect'; mkdir -- '$RemoteTransfer'; chmod 700 -- '$RemoteTransfer'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the protected ISAB01 collection directory.' }
    & scp.exe -- $Manifest "$($Target):$RemoteManifest"
    if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the publication manifest to ISAB01.' }

    $ProtectScript = @'
set -eu
manifest=$1
chmod 600 -- "$manifest"
test "$(/usr/bin/stat -c '%U:%G:%a' "$manifest")" = 'aag:aag:600'
'@
    $EncodedProtectScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($ProtectScript))
    & ssh.exe -o BatchMode=yes $Target "printf %s '$EncodedProtectScript' | /usr/bin/base64 --decode | /bin/sh -s -- '$RemoteManifest'"
    if ($LASTEXITCODE -ne 0) { throw 'The transferred publication manifest has unsafe permissions.' }

    $RemoteScript = @'
set -eu
manifest=$1
snapshot=$2
python=/opt/ehf/current/venv/bin/python
test -x "$python"
cd /opt/ehf/current
PYTHONPATH=/opt/ehf/current "$python" -m app.importer.collect_open_citations \
  --manifest "$manifest" --output "$snapshot"
chmod 600 -- "$snapshot"
test "$(/usr/bin/stat -c '%U:%G:%a' "$snapshot")" = 'aag:aag:600'
'@
    $EncodedScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RemoteScript))
    & ssh.exe -o BatchMode=yes $Target "printf %s '$EncodedScript' | /usr/bin/base64 --decode | /bin/sh -s -- '$RemoteManifest' '$RemoteSnapshot'"
    if ($LASTEXITCODE -ne 0) { throw 'The ISAB01 open-citation collection failed.' }

    & scp.exe -- "$($Target):$RemoteSnapshot" $TemporaryOutput
    if ($LASTEXITCODE -ne 0) { throw 'Could not retrieve the open-citation snapshot from ISAB01.' }
    Move-Item -LiteralPath $TemporaryOutput -Destination $Output -Force
    Write-Output "Open-citation snapshot collected at $Output"
}
finally {
    & ssh.exe -o BatchMode=yes $Target "rm -rf -- '$RemoteTransfer'" 2>$null | Out-Null
    if (Test-Path -LiteralPath $TemporaryOutput) {
        Remove-Item -LiteralPath $TemporaryOutput -Force
    }
}
