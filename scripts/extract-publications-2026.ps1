[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string] $BaseManifestPath,

    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Container })]
    [string] $SourceRoot,

    [Parameter(Mandatory)]
    [string] $OutputDirectory,

    [ValidatePattern('^https?://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?$')]
    [string] $GrobidUrl = '',

    [switch] $ResolvePublicBibliography,

    [ValidatePattern('^[a-z0-9-]+$')]
    [string] $Stem = 'p260922'
)

$ErrorActionPreference = 'Stop'
$Python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "The pinned repository Python runtime is unavailable: $Python"
}

$Arguments = @(
    '-m', 'app.importer.publication_reconciliation',
    '--base-manifest', [IO.Path]::GetFullPath($BaseManifestPath),
    '--source-root', [IO.Path]::GetFullPath($SourceRoot),
    '--output-directory', [IO.Path]::GetFullPath($OutputDirectory),
    '--stem', $Stem
)
if ($GrobidUrl) {
    $Arguments += @('--grobid-url', $GrobidUrl)
}
if ($ResolvePublicBibliography) {
    $Arguments += '--resolve-public-bibliography'
}

& $Python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "Publication corpus reconciliation failed with exit code $LASTEXITCODE."
}
