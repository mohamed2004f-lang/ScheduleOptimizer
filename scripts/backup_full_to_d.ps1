# Full backup: PostgreSQL + uploads to D: drive
param(
    [string]$MirrorRoot = "",
    [int]$RetentionDays = 0,
    [switch]$SkipDbDump
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Read-DotEnvValue([string]$key) {
    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) { return "" }
    foreach ($line in Get-Content $envFile -Encoding UTF8) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith("#")) { continue }
        if ($t -match "^\s*$key\s*=\s*(.*)$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

function Write-Log([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Host $line
    try {
        $logDir = Join-Path $MirrorRoot "logs"
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        Add-Content -Path (Join-Path $logDir "backup.log") -Value $line -Encoding UTF8
    } catch { }
}

if (-not $MirrorRoot) {
    $MirrorRoot = (Read-DotEnvValue "BACKUP_MIRROR_ROOT").Trim()
}
if (-not $MirrorRoot) {
    $MirrorRoot = "D:\ScheduleOptimizer_Backups"
}
if ($RetentionDays -le 0) {
    $rd = (Read-DotEnvValue "BACKUP_RETENTION_DAYS").Trim()
    if ($rd -match "^\d+$") { $RetentionDays = [int]$rd } else { $RetentionDays = 30 }
}

$drive = [System.IO.Path]::GetPathRoot($MirrorRoot)
if (-not (Test-Path $drive)) {
    Write-Error "Drive not available: $drive - set BACKUP_MIRROR_ROOT in .env"
    exit 1
}

$pgLocal = Join-Path $Root "backups\pg_dump"
$pgMirror = Join-Path $MirrorRoot "pg_dump"
$uploadsSrc = Join-Path $Root "backend\uploads"
$uploadsLatest = Join-Path $MirrorRoot "uploads\latest"
$uploadsDaily = Join-Path $MirrorRoot ("uploads\uploads_{0}" -f (Get-Date -Format "yyyyMMdd"))
$stampFile = Join-Path $MirrorRoot "README.txt"

New-Item -ItemType Directory -Force -Path $MirrorRoot, $pgMirror, (Split-Path $uploadsLatest) | Out-Null

if (-not (Test-Path $stampFile)) {
    $readme = @"
ScheduleOptimizer Backups
=========================
Auto-updated daily (scheduled task 23:30).

pg_dump\       - PostgreSQL .dump files
uploads\latest\ - latest attachments mirror
uploads\uploads_YYYYMMDD\ - daily uploads snapshot
logs\backup.log

Restore: see docs/PG_BACKUP.md in the project.
Do NOT upload this folder to GitHub.
"@
    Set-Content -Path $stampFile -Value $readme -Encoding UTF8
}

Write-Log "=== backup start: $MirrorRoot ==="

if (-not $SkipDbDump) {
    $py = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { $py = "python" }
    Write-Log "pg_dump..."
    & $py (Join-Path $Root "scripts\pg_dump_via_env.py")
    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR: pg_dump failed"
        exit 1
    }
}

if (Test-Path $pgLocal) {
    Write-Log "mirror pg_dump to D:"
    New-Item -ItemType Directory -Force -Path $pgMirror | Out-Null
    robocopy $pgLocal $pgMirror *.dump /R:2 /W:5 /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    if ($LASTEXITCODE -ge 8) {
        Write-Log "ERROR: robocopy pg_dump failed ($LASTEXITCODE)"
        exit 1
    }
}

if (Test-Path $uploadsSrc) {
    Write-Log "mirror uploads to latest"
    New-Item -ItemType Directory -Force -Path $uploadsLatest | Out-Null
    robocopy $uploadsSrc $uploadsLatest /E /R:2 /W:5 /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    if ($LASTEXITCODE -ge 8) {
        Write-Log "ERROR: robocopy uploads failed ($LASTEXITCODE)"
        exit 1
    }
    if (-not (Test-Path $uploadsDaily)) {
        Write-Log "daily uploads snapshot"
        Copy-Item -Recurse -Force $uploadsSrc $uploadsDaily
    }
} else {
    Write-Log "WARN: backend\uploads not found - skipped"
}

function Remove-OldFiles([string]$dir, [string]$pattern, [int]$days) {
    if (-not (Test-Path $dir)) { return }
    $cutoff = (Get-Date).AddDays(-$days)
    Get-ChildItem -Path $dir -Filter $pattern -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        ForEach-Object {
            Write-Log "prune $($_.Name)"
            Remove-Item -LiteralPath $_.FullName -Force
        }
}

function Remove-OldDirs([string]$dir, [string]$prefix, [int]$days) {
    if (-not (Test-Path $dir)) { return }
    $cutoff = (Get-Date).AddDays(-$days)
    Get-ChildItem -Path $dir -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "$prefix*" -and $_.LastWriteTime -lt $cutoff } |
        ForEach-Object {
            Write-Log "prune dir $($_.Name)"
            Remove-Item -LiteralPath $_.FullName -Recurse -Force
        }
}

Write-Log "retention $RetentionDays days"
Remove-OldFiles $pgLocal "*.dump" $RetentionDays
Remove-OldFiles $pgMirror "*.dump" $RetentionDays
Remove-OldDirs (Join-Path $MirrorRoot "uploads") "uploads_" $RetentionDays

Write-Log "=== backup OK ==="
exit 0
