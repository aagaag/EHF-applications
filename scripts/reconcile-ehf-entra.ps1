[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $Apply -and -not $WhatIfPreference) {
    throw 'Select -WhatIf for a dry run or -Apply to reconcile the verified EHF groups.'
}
if ($Apply -and $WhatIfPreference) {
    throw 'Select either -WhatIf or -Apply, not both.'
}

$TenantId = '8226a4c2-10fa-4742-b4c0-f4fdb97a0534'
$RequiredAzPath = 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
$ResolvedAzPath = (Get-Command az -ErrorAction Stop).Source
if ([System.IO.Path]::GetFullPath($ResolvedAzPath) -ne $RequiredAzPath) {
    throw 'Get-Command az does not resolve to the required Microsoft SDK Azure CLI.'
}
$script:AzPath = $RequiredAzPath

$ExpectedUsers = @(
    [pscustomobject]@{ Id = 'd5c5fb6a-f9c3-456c-97b1-20b450647f8c'; Name = 'Adriano Aguzzi'; Mail = 'adriano.aguzzi@isab.science'; Type = 'Member' },
    [pscustomobject]@{ Id = '0da50d11-f875-4a4d-8ac8-f7bbd44499d7'; Name = 'Margaryta Schaltegger'; Mail = 'margaryta.schaltegger@isab.science'; Type = 'Member' },
    [pscustomobject]@{ Id = '70a7cbba-44f0-4689-b600-768b9c05ec6c'; Name = 'Elena De Cecco'; Mail = 'elena.dececco@isab.science'; Type = 'Member' },
    [pscustomobject]@{ Id = '7747ffa7-5193-4cc8-9221-08a1dd24b026'; Name = 'Ricky Weissman'; Mail = 'ricky@weissmann.ch'; Type = 'Guest' },
    [pscustomobject]@{ Id = '09d14671-38e1-4763-8d67-512c9787d379'; Name = 'Magdalini Polymenidou'; Mail = 'magdalini.polymenidou@uzh.ch'; Type = 'Guest' }
)
$ExpectedUserById = @{}
foreach ($User in $ExpectedUsers) {
    $ExpectedUserById[$User.Id] = $User
}

$Groups = @(
    [pscustomobject]@{
        Id = '8e199674-d599-45e1-9daa-d138a0b40753'
        LegacyName = 'EHF-Applications-Administrators'
        Name = 'EHF-Administrators'
        MemberIds = @(
            'd5c5fb6a-f9c3-456c-97b1-20b450647f8c',
            '0da50d11-f875-4a4d-8ac8-f7bbd44499d7',
            '70a7cbba-44f0-4689-b600-768b9c05ec6c'
        )
    },
    [pscustomobject]@{
        Id = 'fc584ecb-8be3-4f70-89d0-a5f0ae37f21a'
        LegacyName = 'EHF-Applications-Trustees'
        Name = 'EHF-Trustees'
        MemberIds = @(
            'd5c5fb6a-f9c3-456c-97b1-20b450647f8c',
            '7747ffa7-5193-4cc8-9221-08a1dd24b026',
            '09d14671-38e1-4763-8d67-512c9787d379'
        )
    }
)

function Invoke-GraphRead {
    param([Parameter(Mandatory = $true)][string]$Url)

    $Output = @(& $script:AzPath rest --only-show-errors --method GET --url $Url --output json 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw 'A required Microsoft Graph read failed.'
    }
    try {
        return ($Output -join "`n") | ConvertFrom-Json
    }
    catch {
        throw 'Microsoft Graph returned an invalid response.'
    }
}

function Invoke-GraphWrite {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$Action
    )

    if (-not $Apply) {
        Write-Output ("PLAN: {0}" -f $Action)
        return
    }
    if (-not $PSCmdlet.ShouldProcess($Target, $Action)) {
        return
    }
    $Output = @(& $script:AzPath @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw 'A bounded Microsoft Graph write failed.'
    }
}

function Assert-TenantAndUsers {
    $Account = @(& $script:AzPath account show --output json 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw 'The Azure CLI account is unavailable.'
    }
    $AccountState = ($Account -join "`n") | ConvertFrom-Json
    if ($AccountState.tenantId -ne $TenantId) {
        throw 'The Azure CLI is connected to the wrong Microsoft Entra tenant.'
    }

    foreach ($Expected in $ExpectedUsers) {
        $Url = "https://graph.microsoft.com/v1.0/users/$($Expected.Id)?`$select=id,displayName,mail,userType,accountEnabled"
        $Actual = Invoke-GraphRead -Url $Url
        if (
            $Actual.id -ne $Expected.Id -or
            $Actual.mail -ne $Expected.Mail -or
            $Actual.userType -ne $Expected.Type -or
            $Actual.accountEnabled -ne $true
        ) {
            throw ("The verified identity for {0} no longer matches its approved Entra object." -f $Expected.Name)
        }
    }
}

function Get-GroupState {
    param([Parameter(Mandatory = $true)]$Definition)

    $GroupUrl = "https://graph.microsoft.com/v1.0/groups/$($Definition.Id)?`$select=id,displayName"
    $MembersUrl = "https://graph.microsoft.com/v1.0/groups/$($Definition.Id)/members?`$select=id"
    $Group = Invoke-GraphRead -Url $GroupUrl
    $Members = Invoke-GraphRead -Url $MembersUrl
    if ($Group.id -ne $Definition.Id) {
        throw 'Microsoft Graph returned the wrong EHF group object.'
    }
    if ($Group.displayName -notin @($Definition.LegacyName, $Definition.Name)) {
        throw ("The EHF group {0} has an unexpected display name." -f $Definition.Id)
    }
    $ActualMemberIds = @($Members.value | ForEach-Object { [string]$_.id })
    $Unexpected = @($ActualMemberIds | Where-Object { $_ -notin $Definition.MemberIds })
    if ($Unexpected.Count -gt 0) {
        throw ("Unexpected members are present in {0}; no write was attempted." -f $Definition.Name)
    }
    return [pscustomobject]@{
        Definition = $Definition
        DisplayName = [string]$Group.displayName
        MemberIds = $ActualMemberIds
        MissingMemberIds = @($Definition.MemberIds | Where-Object { $_ -notin $ActualMemberIds })
    }
}

Assert-TenantAndUsers
$InitialStates = @($Groups | ForEach-Object { Get-GroupState -Definition $_ })

foreach ($State in $InitialStates) {
    $Definition = $State.Definition
    if ($State.DisplayName -ne $Definition.Name) {
        $Body = @{ displayName = $Definition.Name } | ConvertTo-Json -Compress
        Invoke-GraphWrite -Arguments @(
            'rest', '--only-show-errors', '--method', 'PATCH',
            '--url', "https://graph.microsoft.com/v1.0/groups/$($Definition.Id)",
            '--headers', 'Content-Type=application/json', '--body', $Body, '--output', 'none'
        ) -Target $Definition.Id -Action ("Rename {0} to {1}" -f $State.DisplayName, $Definition.Name)
    }
    foreach ($MemberId in $State.MissingMemberIds) {
        $Expected = $ExpectedUserById[$MemberId]
        if ($null -eq $Expected) {
            throw 'A desired group member is not in the verified identity inventory.'
        }
        $Body = @{ '@odata.id' = "https://graph.microsoft.com/v1.0/directoryObjects/$MemberId" } | ConvertTo-Json -Compress
        Invoke-GraphWrite -Arguments @(
            'rest', '--only-show-errors', '--method', 'POST',
            '--url', "https://graph.microsoft.com/v1.0/groups/$($Definition.Id)/members/`$ref",
            '--headers', 'Content-Type=application/json', '--body', $Body, '--output', 'none'
        ) -Target $Definition.Id -Action ("Add {0} to {1}" -f $Expected.Name, $Definition.Name)
    }
}

if (-not $Apply) {
    Write-Output 'EHF Entra reconciliation dry run completed without writes.'
    return
}

$FinalStates = @($Groups | ForEach-Object { Get-GroupState -Definition $_ })
foreach ($State in $FinalStates) {
    if (
        $State.DisplayName -ne $State.Definition.Name -or
        $State.MissingMemberIds.Count -ne 0 -or
        $State.MemberIds.Count -ne $State.Definition.MemberIds.Count
    ) {
        throw ("The final EHF group state did not verify for {0}." -f $State.Definition.Name)
    }
}

Write-Output 'EHF Entra groups now have the exact approved names and memberships.'
