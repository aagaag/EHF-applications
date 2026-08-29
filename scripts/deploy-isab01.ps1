param(
    [switch] $Apply,
    [ValidatePattern('^[0-9a-f]{40}$')] [string] $Rollback = '',
    [ValidatePattern('^/[A-Za-z0-9._/-]+$')] [string] $SqlAdminCredentialPath = '',
    [switch] $WhatIf
)

$ErrorActionPreference = 'Stop'
$Target = 'isab-db01-hestia'
$Python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$InstalledHelper = '/usr/local/sbin/ehf-deploy'

if (@($Apply, [bool]$Rollback | Where-Object { $_ }).Count -gt 1) {
    throw 'Select either -Apply or -Rollback, not both.'
}
if (-not $Apply -and -not $Rollback -and -not $WhatIf) {
    throw 'Select -Apply, -Rollback <40-hex-commit>, or -WhatIf.'
}

$Head = (git rev-parse HEAD).Trim()
if ($Head -notmatch '^[0-9a-f]{40}$') {
    throw 'The tested Git commit could not be resolved.'
}

function Assert-DeployRepositoryState {
    $Branch = (git branch --show-current).Trim()
    $Remote = (git rev-parse origin/main).Trim()
    $Status = @(git status --porcelain=v1)
    if ($Branch -ne 'main' -or $Head -ne $Remote -or $Status.Count -ne 0) {
        throw 'Deploy from a clean main checkout exactly synchronized with origin/main.'
    }
}

if ($WhatIf) {
    Write-Output "WhatIf: would deploy immutable EHF commit $Head to ISAB01."
    Write-Output 'WhatIf: would create exact git archive bytes, run local and Linux safety tests, then validate SQL before activation.'
    Write-Output 'WhatIf: would atomically switch /opt/ehf/current only after all pre-activation checks pass.'
    Write-Output 'WhatIf: would keep invitations and production mail disabled and would not alter Cloudflare, DNS, or outbound communications.'
    Write-Output 'Apply requires clean main exactly synchronized with origin/main and an explicit protected SQL administrator credential path.'
    return
}

if ($Rollback) {
    & ssh.exe -o BatchMode=yes $Target "sudo -n /usr/bin/python3 '$InstalledHelper' --rollback '$Rollback'"
    if ($LASTEXITCODE -ne 0) {
        throw 'The named immutable EHF rollback failed.'
    }
    return
}

if (-not $SqlAdminCredentialPath) {
    throw 'Apply requires -SqlAdminCredentialPath with the protected path on ISAB01; do not provide a credential value.'
}
Assert-DeployRepositoryState

& $Python -m pytest infra\test-install-isab01.py tests\test_deployment_contract.py -q
if ($LASTEXITCODE -ne 0) {
    throw 'The EHF installer/deployment safety tests failed.'
}

$TempRoot = Join-Path ([IO.Path]::GetTempPath()) "ehf-$PID"
$Archive = Join-Path $TempRoot 'r.tar'
$RemoteArchive = "/tmp/ehf-$PID.tar"
$RemoteHelper = "/tmp/ehf-$PID.py"
$RemoteTest = "/tmp/ehf-$PID-test.py"
$LocalHelper = Join-Path $PSScriptRoot '..\infra\install-isab01.py'
$LocalTest = Join-Path $PSScriptRoot '..\infra\test-install-isab01.py'

try {
    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
    git -c core.autocrlf=false archive --format=tar --output=$Archive $Head
    if ($LASTEXITCODE -ne 0) {
        throw 'The exact tested release archive could not be created.'
    }
    & scp.exe -- $Archive "${Target}:${RemoteArchive}"
    if ($LASTEXITCODE -ne 0) { throw 'The release archive could not be staged on ISAB01.' }
    & scp.exe -- $LocalHelper "${Target}:${RemoteHelper}"
    if ($LASTEXITCODE -ne 0) { throw 'The reviewed deployment helper could not be staged on ISAB01.' }
    & scp.exe -- $LocalTest "${Target}:${RemoteTest}"
    if ($LASTEXITCODE -ne 0) { throw 'The Linux installer safety test could not be staged on ISAB01.' }
    & ssh.exe -o BatchMode=yes $Target "sudo -n /usr/bin/install -o root -g root -m 0755 '$RemoteHelper' '$InstalledHelper'"
    if ($LASTEXITCODE -ne 0) { throw 'The reviewed deployment helper could not be installed.' }
    & ssh.exe -o BatchMode=yes $Target "sudo -n /usr/bin/python3 '$InstalledHelper' --archive '$RemoteArchive' --commit '$Head' --sql-admin-credential '$SqlAdminCredentialPath' --apply"
    if ($LASTEXITCODE -ne 0) { throw 'The EHF ISAB01 deployment failed.' }
} finally {
    & ssh.exe -o BatchMode=yes $Target "rm -f -- '$RemoteArchive' '$RemoteHelper' '$RemoteTest'" 2>$null | Out-Null
    if (Test-Path -LiteralPath $TempRoot) {
        $ResolvedTemp = (Resolve-Path -LiteralPath $TempRoot).Path
        $ExpectedTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        if ($ResolvedTemp.StartsWith($ExpectedTempRoot, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $ResolvedTemp -Recurse -Force
        }
    }
}
