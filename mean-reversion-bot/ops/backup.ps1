param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
# Use standard PGHOST/PGPORT/PGDATABASE/PGUSER and a protected PGPASSFILE.
# Credentials never appear in process arguments or console output.
$backupDirectory = [System.IO.Path]::GetFullPath($Destination)
if (-not (Test-Path -LiteralPath $backupDirectory -PathType Container)) {
    throw 'Destination must be an existing backup directory'
}
$backupPath = Join-Path $backupDirectory ('mrbot-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '.dump')
if (Test-Path -LiteralPath $backupPath) { throw 'Backup already exists' }
& pg_dump --format=custom --no-owner --no-acl --file $backupPath
if ($LASTEXITCODE -ne 0) { throw 'Backup failed; inspect the partial archive before retrying' }
& pg_restore --list $backupPath | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Archive verification failed' }
Write-Output "Backup created: $backupPath"
