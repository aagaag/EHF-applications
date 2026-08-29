[CmdletBinding(DefaultParameterSetName = 'PlanOnly')]
param(
    [Parameter(Mandatory)] [ValidateScript({ Test-Path -LiteralPath $_ -PathType Container })] [string] $SourcePackage,
    [Parameter(Mandatory)] [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })] [string] $IdentityPartsPath,
    [Parameter(Mandatory)] [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })] [string] $FolderAliasesPath,
    [Parameter(Mandatory)] [ValidatePattern('^[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}$')] [string] $CallId,
    [ValidateNotNullOrEmpty()] [string] $RegisterRelativePath = 'Call_2026_applicant_metrics.docx',
    [ValidatePattern('^/[A-Za-z0-9._/-]+$')] [string] $SqlAdminCredentialPath = '',
    [Parameter(ParameterSetName = 'Apply', Mandatory)] [switch] $Apply
)

$ErrorActionPreference = 'Stop'
$Target = 'isab-db01-hestia'
$TransferId = [Guid]::NewGuid().ToString('N')
$Archive = Join-Path ([IO.Path]::GetTempPath()) "ehf-$TransferId.tar"
$RemoteTransfer = "/home/aag/.ehf-transfer/$TransferId"
$RemoteArchive = "$RemoteTransfer/source.tar"
$RemoteIdentity = "$RemoteTransfer/identity.json"
$RemoteAliases = "$RemoteTransfer/aliases.json"
$EncodedCallId = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($CallId))
$EncodedRegister = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RegisterRelativePath))
$ApplyFlag = if ($Apply) { '--apply' } else { '' }
if ($Apply -and -not $SqlAdminCredentialPath) {
    throw 'Apply requires the protected SQL administrator credential path; do not provide a credential value.'
}

try {
    # Source content is transferred only to an owned ISAB01 staging directory, never into Git.
    & tar.exe -cf $Archive -C $SourcePackage .
    if ($LASTEXITCODE -ne 0) { throw 'Could not package the selected source directory.' }
    & ssh.exe -o BatchMode=yes $Target "umask 077; mkdir -p -- '/home/aag/.ehf-transfer'; chmod 700 -- '/home/aag/.ehf-transfer'; mkdir -- '$RemoteTransfer'; chmod 700 -- '$RemoteTransfer'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the protected ISAB01 transfer directory.' }
    & scp.exe -q $Archive "${Target}:$RemoteArchive"
    if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the source package to ISAB01.' }
    & scp.exe -q $IdentityPartsPath "${Target}:$RemoteIdentity"
    if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the reviewed identity map to ISAB01.' }
    & scp.exe -q $FolderAliasesPath "${Target}:$RemoteAliases"
    if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the reviewed folder-alias map to ISAB01.' }
    & ssh.exe -o BatchMode=yes $Target "chmod 600 -- '$RemoteArchive' '$RemoteIdentity' '$RemoteAliases'; if find '$RemoteTransfer' -maxdepth 1 -type f -perm /077 -print -quit | grep -q .; then exit 2; fi"
    if ($LASTEXITCODE -ne 0) { throw 'The protected ISAB01 transfer files have unsafe permissions.' }

    $RemoteScript = @'
set -eu
archive=$1
identity=$2
aliases=$3
call_id=$(printf '%s' "$4" | /usr/bin/base64 --decode)
register=$(printf '%s' "$5" | /usr/bin/base64 --decode)
apply_flag=$6
sql_admin_path=$7
test "$(/usr/bin/stat -c '%U:%G:%a' "$archive")" = 'aag:aag:600'
test "$(/usr/bin/stat -c '%U:%G:%a' "$identity")" = 'aag:aag:600'
test "$(/usr/bin/stat -c '%U:%G:%a' "$aliases")" = 'aag:aag:600'
/usr/bin/install -d -o root -g root -m 0700 /root/ehf-import
stage=$( /usr/bin/mktemp -d /root/ehf-import/call-2026.XXXXXX )
cleanup() {
  /usr/bin/rm -f -- "$archive" "$identity" "$aliases"
  case "$stage" in /root/ehf-import/call-2026.*) /usr/bin/rm -rf -- "$stage" ;; *) exit 2 ;; esac
}
trap cleanup EXIT
/usr/bin/chmod 0700 /root/ehf-import "$stage"
/usr/bin/tar -tf "$archive" | /usr/bin/grep -Eq '(^/|(^|/)\.\.(/|$))' && exit 2 || :
/usr/bin/tar --no-same-owner --no-same-permissions -xf "$archive" -C "$stage"
test ! -e "$stage/../invalid"
/usr/bin/install -m 0600 -o root -g root "$identity" "$stage/identity-parts.json"
/usr/bin/install -m 0600 -o root -g root "$aliases" "$stage/folder-aliases.json"
release=$( /usr/bin/readlink -f /opt/ehf/current )
python="$release/venv/bin/python"
cd "$release"
if [ "$apply_flag" = '--apply' ]; then
  /usr/bin/systemd-run --quiet --wait --pipe --collect \
    --property=Type=exec \
    --property=LoadCredential=document-keyring:/etc/ehf/document-keyring \
    /bin/sh -c 'set -eu; release=$1; shift; set -a; . /etc/ehf/ehf.env; set +a; export EHF_DOCUMENT_ENCRYPTION_KEYRING_PATH="$CREDENTIALS_DIRECTORY/document-keyring"; cd "$release"; exec "$@"' \
    sh "$release" "$python" -m app.importer.run --source-root "$stage" --register "$stage/$register" --identity-parts "$stage/identity-parts.json" --folder-aliases "$stage/folder-aliases.json" --call-id "$call_id" --apply --sql-admin-credential-file "$sql_admin_path"
else
  "$python" -m app.importer.run --source-root "$stage" --register "$stage/$register" --identity-parts "$stage/identity-parts.json" --folder-aliases "$stage/folder-aliases.json" --call-id "$call_id"
fi
'@
    $EncodedScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RemoteScript.Replace("`r`n", "`n")))
    & ssh.exe -o BatchMode=yes $Target "printf %s '$EncodedScript' | /usr/bin/base64 --decode | sudo -n /bin/sh -s -- '$RemoteArchive' '$RemoteIdentity' '$RemoteAliases' '$EncodedCallId' '$EncodedRegister' '$ApplyFlag' '$SqlAdminCredentialPath'"
    if ($LASTEXITCODE -ne 0) { throw 'The root-mediated ISAB01 import operation failed.' }
}
finally {
    Remove-Item -LiteralPath $Archive -Force -ErrorAction SilentlyContinue
    & ssh.exe -o BatchMode=yes $Target "rm -rf -- '$RemoteTransfer'" 2>$null | Out-Null
}
