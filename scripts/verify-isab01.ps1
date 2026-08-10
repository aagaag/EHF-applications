param(
    [ValidatePattern('^[0-9a-f]{40}$')] [string] $ExpectedCommit = ''
)

$ErrorActionPreference = 'Stop'
$Target = 'aag@10.10.20.29'
$CommitCheck = if ($ExpectedCommit) { "test `"`$commit`" = '$ExpectedCommit';" } else { '' }
$RemoteCheck = "set -eu; release=`$(readlink -f /opt/ehf/current); case `"`$release`" in /opt/ehf/r/[0-9a-f][0-9a-f]*) ;; *) exit 2 ;; esac; commit=`$(cat `"`$release/.commit`"); case `"`$commit`" in [0-9a-f][0-9a-f]*) ;; *) exit 2 ;; esac; $CommitCheck systemctl is-active --quiet ehf.service; systemctl show ehf.service --property=ProtectSystem --property=ProtectHome --property=PrivateTmp --property=NoNewPrivileges --property=CapabilityBoundingSet --property=RestrictAddressFamilies; /usr/sbin/nginx -t; /usr/bin/curl --fail --silent --show-error --max-time 5 --header 'Host: ehf.isab.science' http://127.0.0.1:8086/health/ready >/dev/null; /usr/bin/ss -ltn '( sport = :8086 )' | /usr/bin/grep -F '127.0.0.1:8086' >/dev/null; /usr/bin/ss -ltn '( sport = :1433 )' | /usr/bin/grep -F '127.0.0.1:1433' >/dev/null; /usr/bin/grep -qx 'EHF_INVITATIONS_ENABLED=false' /etc/ehf/ehf.env; /usr/bin/grep -qx 'EHF_PRODUCTION_MAIL_ENABLED=false' /etc/ehf/ehf.env; /usr/bin/grep -Fqx 'server_name ehf.isab.science;' /etc/nginx/sites-available/ehf; /usr/bin/grep -Fqx 'proxy_pass http://127.0.0.1:8086;' /etc/nginx/sites-available/ehf; printf 'EHF verification passed for %s`n' `"`$commit`""

& ssh.exe -o BatchMode=yes $Target "sudo -n /bin/sh -c '$RemoteCheck'"
if ($LASTEXITCODE -ne 0) {
    throw 'ISAB01 EHF verification failed.'
}
