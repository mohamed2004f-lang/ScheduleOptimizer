# Stop local app.py on port 5000 — NEVER kill Docker Desktop / container proxy.
param(
    [switch]$ForceAll
)

$ErrorActionPreference = 'SilentlyContinue'

function Test-IsDockerPortProcess {
    param([int]$ProcessId)
    if (-not $ProcessId) { return $false }
    try {
        $proc = Get-Process -Id $ProcessId -ErrorAction Stop
    } catch {
        return $false
    }
    $name = if ($proc.ProcessName) { $proc.ProcessName.ToLower() } else { '' }
    if ($name -match '^(docker|com\.docker|wsl|wslrelay|vmcompute|vmmem)$') {
        return $true
    }
    if ($name -match '^docker') {
        return $true
    }
    try {
        $path = if ($proc.Path) { $proc.Path.ToLower() } else { '' }
        if ($path -match 'docker|dockerdesktop|wsl') {
            return $true
        }
    } catch { }
    return $false
}

function Test-IsLocalPythonApp {
    param([int]$ProcessId)
    if (-not $ProcessId) { return $false }
    try {
        $proc = Get-Process -Id $ProcessId -ErrorAction Stop
    } catch {
        return $false
    }
    $name = if ($proc.ProcessName) { $proc.ProcessName.ToLower() } else { '' }
    if ($name -notmatch '^python') {
        return $false
    }
    try {
        $path = if ($proc.Path) { $proc.Path.ToLower() } else { '' }
        if ($path -match 'scheduleoptimizer|\.venv') {
            return $true
        }
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop).CommandLine
        if ($cmd -and ($cmd -match 'app\.py|ScheduleOptimizer')) {
            return $true
        }
    } catch { }
    return $true
}

$pids = @(
    Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
)

if (-not $pids) {
    Write-Host 'No listener on port 5000'
    exit 0
}

foreach ($procId in $pids) {
    if (-not $procId) { continue }
    if (Test-IsDockerPortProcess -ProcessId $procId) {
        Write-Host ("Skipping Docker-related PID " + $procId)
        continue
    }
    if (-not $ForceAll -and -not (Test-IsLocalPythonApp -ProcessId $procId)) {
        $pname = (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName
        Write-Host ("Skipping non-local-app PID " + $procId + " (" + $pname + ")")
        continue
    }
    Stop-Process -Id $procId -Force
    Write-Host ('Stopped PID ' + $procId)
}
