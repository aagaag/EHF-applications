[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$SourceRoot,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$OutputRoot
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'The approved repository Python runtime is unavailable.'
}

Push-Location -LiteralPath $repositoryRoot
try {
    & $python -m app.importer.inventory --source-root $SourceRoot --output-root $OutputRoot
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
