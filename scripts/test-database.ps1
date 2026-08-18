[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatabaseName,

    [string]$ServerInstance = 'ISAB01'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$requiredPrefix = 'EHFApplications_Test'
if (-not $DatabaseName.StartsWith($requiredPrefix, [System.StringComparison]::Ordinal)) {
    throw 'DatabaseName must start exactly with EHFApplications_Test.'
}
if ([string]::IsNullOrWhiteSpace($ServerInstance)) {
    throw 'ServerInstance is required.'
}

function Quote-SqlIdentifier {
    param([Parameter(Mandatory = $true)][string]$Value)
    return '[' + $Value.Replace(']', ']]') + ']'
}

function Quote-SqlLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "N'" + $Value.Replace("'", "''") + "'"
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$migrationDirectory = Join-Path $projectRoot 'database\migrations'
$validationDirectory = Join-Path $projectRoot 'database\tests'
$python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'The bundled Python runtime is unavailable.'
}

$migrationFiles = @(Get-ChildItem -LiteralPath $migrationDirectory -File -Filter '*.sql' | Sort-Object Name)
$validationFiles = @(Get-ChildItem -LiteralPath $validationDirectory -File -Filter '*.sql' | Sort-Object Name)
if (($migrationFiles.Name -join ',') -ne
    '001_database_contract.sql,002_application_core.sql,003_audit_and_preferences.sql,004_audit_and_preference_hardening.sql,005_application_permissions.sql,006_user_preference_read.sql,007_document_store.sql,008_import_provenance.sql,009_document_permissions.sql,010_report_export_audit.sql,011_applicant_access.sql,012_applicant_drafts.sql,013_applicant_confirmations.sql,014_applicant_projection.sql,015_applicant_document_slots.sql,016_entra_applicant_workflow.sql') {
    throw 'The isolated test requires exactly migrations 001 through 016.'
}
if (($validationFiles.Name -join ',') -ne
    '001_validate_database_contract.sql,002_validate_application_core.sql,003_validate_audit_and_preferences.sql,004_validate_audit_and_preference_hardening.sql,005_validate_application_permissions.sql,006_validate_user_preference_read.sql,007_validate_document_store.sql,008_validate_import_provenance.sql,009_validate_document_permissions.sql,010_validate_report_export_audit.sql,011_validate_applicant_access.sql,012_validate_applicant_drafts.sql,013_validate_applicant_confirmations.sql,014_validate_applicant_projection.sql,015_validate_applicant_document_slots.sql,016_validate_entra_applicant_workflow.sql') {
    throw 'The isolated test requires exactly validators 001 through 016.'
}

$sqlcmdCommand = Get-Command 'sqlcmd' -ErrorAction SilentlyContinue
if ($null -eq $sqlcmdCommand) {
    throw 'sqlcmd is unavailable; install Microsoft SQL Server command-line tools.'
}
$sqlcmd = $sqlcmdCommand.Source
$quotedDatabase = Quote-SqlIdentifier -Value $DatabaseName
$databaseLiteral = Quote-SqlLiteral -Value $DatabaseName
$createdDatabase = $false

function Invoke-TrustedSqlcmd {
    param(
        [Parameter(Mandatory = $true)][string]$Database,
        [string]$Query,
        [string]$InputFile,
        [switch]$Raw
    )

    $arguments = @(
        '-S', $ServerInstance,
        '-E',
        '-C',
        '-I',
        '-b',
        '-V', '11',
        '-r', '1',
        '-d', $Database
    )
    if ($Query) {
        $arguments += @('-Q', $Query)
    }
    elseif ($InputFile) {
        $arguments += @('-i', $InputFile)
    }
    else {
        throw 'A SQL query or input file is required.'
    }
    if ($Raw) {
        $arguments += @('-h', '-1', '-W')
    }

    $output = @(& $sqlcmd @arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw 'A trusted SQL verification command failed.'
    }
    return $output
}

$migrationRunner = @'
import os
import sys
from pathlib import Path

import pyodbc

from app.migrations import MigrationError, apply_migrations, discover_migrations


def odbc_value(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


connection = None
try:
    connection = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={odbc_value(os.environ['EHF_TEST_SQL_SERVER'])};"
        f"DATABASE={odbc_value(os.environ['EHF_TEST_SQL_DATABASE'])};"
        "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;"
        "Connection Timeout=15;",
        autocommit=False,
    )
    connection.execute(
        "SET ANSI_NULLS ON; SET QUOTED_IDENTIFIER ON; SET ANSI_PADDING ON; "
        "SET ANSI_WARNINGS ON; SET ARITHABORT ON; "
        "SET CONCAT_NULL_YIELDS_NULL ON; SET NUMERIC_ROUNDABORT OFF;"
    )
    count = apply_migrations(
        connection,
        discover_migrations(Path(os.environ["EHF_TEST_MIGRATION_DIRECTORY"])),
    )
except MigrationError as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(2) from None
except Exception:
    print("The isolated SQL connection or migration run failed.", file=sys.stderr)
    raise SystemExit(2) from None
finally:
    if connection is not None:
        connection.close()

print(f"Applied {count} migration(s).")
'@

function Invoke-MigrationRunner {
    $env:EHF_TEST_SQL_SERVER = $ServerInstance
    $env:EHF_TEST_SQL_DATABASE = $DatabaseName
    $env:EHF_TEST_MIGRATION_DIRECTORY = $migrationDirectory
    $output = @(& $python -c $migrationRunner 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw ('The migration runner failed safely: ' + ($output -join ' '))
    }
    return $output
}

try {
    $existsOutput = Invoke-TrustedSqlcmd -Database 'master' -Raw -Query (
        'SET NOCOUNT ON; SELECT CASE WHEN DB_ID(' + $databaseLiteral +
        ') IS NULL THEN 0 ELSE 1 END;'
    )
    if (($existsOutput -join '').Trim() -ne '0') {
        throw 'The requested isolated test database already exists; it will not be reused or deleted.'
    }

    Invoke-TrustedSqlcmd -Database 'master' -Query ('CREATE DATABASE ' + $quotedDatabase + ';') |
        Out-Null
    $createdDatabase = $true

    $firstRun = @(Invoke-MigrationRunner)
    if (($firstRun -join "`n") -notmatch 'Applied 16 migration\(s\)\.') {
        throw 'The first migration run did not apply exactly sixteen migrations.'
    }
    $firstRun | Write-Output

    foreach ($validationFile in $validationFiles) {
        Invoke-TrustedSqlcmd -Database $DatabaseName -InputFile $validationFile.FullName |
            Write-Output
    }

    $secondRun = @(Invoke-MigrationRunner)
    if (($secondRun -join "`n") -notmatch 'Applied 0 migration\(s\)\.') {
        throw 'The second migration run was not an idempotent no-op.'
    }
    $secondRun | Write-Output
}
finally {
    Remove-Item Env:EHF_TEST_SQL_SERVER -ErrorAction SilentlyContinue
    Remove-Item Env:EHF_TEST_SQL_DATABASE -ErrorAction SilentlyContinue
    Remove-Item Env:EHF_TEST_MIGRATION_DIRECTORY -ErrorAction SilentlyContinue

    if ($createdDatabase) {
        if (-not $DatabaseName.StartsWith($requiredPrefix, [System.StringComparison]::Ordinal)) {
            throw 'Cleanup refused a database outside the EHFApplications_Test prefix.'
        }
        $dropQuery =
            'IF DB_ID(' + $databaseLiteral + ') IS NOT NULL BEGIN ' +
            'ALTER DATABASE ' + $quotedDatabase + ' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; ' +
            'DROP DATABASE ' + $quotedDatabase + '; END;'
        Invoke-TrustedSqlcmd -Database 'master' -Query $dropQuery | Out-Null
        Write-Output ('Dropped explicitly created test database ' + $DatabaseName + '.')
    }
}
