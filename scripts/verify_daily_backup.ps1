# تحقق من مهمة النسخ اليومي ووجود آخر نسخة
param(
    [int]$MaxAgeHours = 36
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot

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

$MirrorRoot = (Read-DotEnvValue "BACKUP_MIRROR_ROOT").Trim()
if (-not $MirrorRoot) { $MirrorRoot = "D:\ScheduleOptimizer_Backups" }

Write-Host "Mirror: $MirrorRoot"
$task = Get-ScheduledTask -TaskName "ScheduleOptimizer_DB_Backup_Daily" -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName "ScheduleOptimizer_DB_Backup_Daily"
    Write-Host "[OK] Daily task exists. State=$($task.State) LastRun=$($info.LastRunTime) LastResult=$($info.LastTaskResult)"
} else {
    Write-Host "[FAIL] Daily task missing. Run: scripts\setup_backup_tasks.bat"
}

$pgDirs = @(
    (Join-Path $MirrorRoot "pg_dump"),
    (Join-Path $Root "backups\pg_dump")
)
$latest = $null
foreach ($d in $pgDirs) {
    if (-not (Test-Path $d)) { continue }
    $f = Get-ChildItem -Path $d -Filter "*.dump" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($f -and (-not $latest -or $f.LastWriteTime -gt $latest.LastWriteTime)) {
        $latest = $f
    }
}

if ($latest) {
    $ageH = [math]::Round(((Get-Date) - $latest.LastWriteTime).TotalHours, 1)
    if ($ageH -le $MaxAgeHours) {
        Write-Host "[OK] Latest dump: $($latest.FullName) age=${ageH}h"
    } else {
        Write-Host "[WARN] Latest dump is old (${ageH}h): $($latest.FullName)"
        Write-Host "       Run: scripts\backup_full_now.bat"
    }
} else {
    Write-Host "[FAIL] No .dump found. Run: scripts\backup_full_now.bat"
}

$uploads = Join-Path $MirrorRoot "uploads\latest"
if (Test-Path $uploads) {
    Write-Host "[OK] Uploads mirror exists: $uploads"
} else {
    Write-Host "[WARN] Uploads mirror missing: $uploads"
}
