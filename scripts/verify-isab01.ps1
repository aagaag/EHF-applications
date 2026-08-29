param(
    [ValidatePattern('^[0-9a-f]{40}$')] [string] $ExpectedCommit = '',
    [switch] $WhatIf
)

$ErrorActionPreference = 'Stop'
$Target = 'isab-db01-hestia'
$ExpectedCommitCheck = if ($ExpectedCommit) { "test `"`$commit`" = '$ExpectedCommit'" } else { ':' }

if ($WhatIf) {
    Write-Output 'WhatIf: would verify the validated immutable release link and commit marker.'
    Write-Output 'WhatIf: would verify EHF systemd hardening, Nginx syntax/site binding, loopback SQL and Uvicorn listeners, and readiness.'
    Write-Output 'WhatIf: would verify invitations and production mail remain disabled.'
    return
}

$RemoteCheck = @'
set -eu
release=$(readlink -f /opt/ehf/current)
commit=$(cat "$release/.commit")
printf '%s' "$commit" | /usr/bin/grep -Eq '^[0-9a-f]{40}$'
test "$release" = "/opt/ehf/r/$commit"
__EXPECTED_COMMIT_CHECK__
systemctl is-active --quiet ehf.service
systemctl show ehf.service --property=ProtectSystem --property=ProtectHome --property=PrivateTmp --property=NoNewPrivileges --property=CapabilityBoundingSet --property=RestrictAddressFamilies
/usr/sbin/nginx -t
/usr/bin/curl --fail --silent --show-error --max-time 5 --header 'Host: ehf.isab.science' http://127.0.0.1:8087/health/ready >/dev/null
/usr/bin/ss -ltn '( sport = :8087 )' | /usr/bin/grep -F '127.0.0.1:8087' >/dev/null
/usr/bin/ss -ltn '( sport = :1433 )' | /usr/bin/grep -F '127.0.0.1:1433' >/dev/null
/usr/bin/grep -qx 'EHF_INVITATIONS_ENABLED=false' /etc/ehf/ehf.env
/usr/bin/grep -qx 'EHF_PRODUCTION_MAIL_ENABLED=false' /etc/ehf/ehf.env
/usr/bin/grep -Eq '^[[:space:]]*server_name[[:space:]]+ehf\.isab\.science;[[:space:]]*$' /etc/nginx/sites-available/ehf
/usr/bin/grep -Eq '^[[:space:]]*proxy_pass[[:space:]]+http://127\.0\.0\.1:8087;[[:space:]]*$' /etc/nginx/sites-available/ehf
printf 'EHF verification passed for %s\n' "$commit"
'@.Replace('__EXPECTED_COMMIT_CHECK__', $ExpectedCommitCheck).Replace("`r`n", "`n")
$EncodedRemoteCheck = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RemoteCheck))

& ssh.exe -o BatchMode=yes $Target "printf %s '$EncodedRemoteCheck' | /usr/bin/base64 --decode | sudo -n /bin/sh"
if ($LASTEXITCODE -ne 0) {
    throw 'ISAB01 EHF verification failed.'
}
