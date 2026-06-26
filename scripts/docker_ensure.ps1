# Start Docker Desktop (if needed) and wait until the engine responds reliably.
param(
    [int]$MaxWaitSeconds = 180,
    [switch]$WaitOnly
)

$ErrorActionPreference = "SilentlyContinue"

function Test-DockerEngine {
    if (-not (Test-Path "\\.\pipe\dockerDesktopLinuxEngine")) {
        return $false
    }
    $serverVer = (docker version --format "{{.Server.Version}}" 2>$null | Out-String).Trim()
    if (-not $serverVer) {
        return $false
    }
    $null = docker ps 2>$null
    return $LASTEXITCODE -eq 0
}

function Test-DockerDesktopRunning {
    $names = @('Docker Desktop', 'com.docker.backend', 'com.docker.service')
    foreach ($n in $names) {
        if (Get-Process -Name $n -ErrorAction SilentlyContinue) {
            return $true
        }
    }
    return $false
}

if (Test-DockerEngine) {
    Write-Host "Docker engine: OK (server $((docker version --format '{{.Server.Version}}' 2>$null)))"
    exit 0
}

if ($WaitOnly -or (Test-DockerDesktopRunning)) {
    Write-Host "Waiting for Docker engine (already running or wait-only mode)..."
    $deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        if (Test-DockerEngine) {
            Write-Host "Docker engine ready."
            exit 0
        }
        Write-Host "Waiting for Docker engine..."
    }
    Write-Host "Docker engine did not become ready within ${MaxWaitSeconds}s." -ForegroundColor Red
    exit 1
}

$exe = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
if (-not (Test-Path $exe)) {
    Write-Host "Docker Desktop not installed at: $exe" -ForegroundColor Red
    exit 1
}

Write-Host "Starting Docker Desktop..."
Start-Process $exe | Out-Null

$deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    if (Test-DockerEngine) {
        Write-Host "Docker engine ready."
        docker version
        exit 0
    }
    Write-Host "Waiting for Docker engine..."
}

Write-Host "Docker engine did not become ready within ${MaxWaitSeconds}s." -ForegroundColor Red
Write-Host ""
Write-Host "Try manually:" -ForegroundColor Yellow
Write-Host "  1. Open Docker Desktop from Start menu and wait until Engine running" -ForegroundColor Yellow
Write-Host "  2. Right-click Docker tray icon -> Restart" -ForegroundColor Yellow
Write-Host "  3. In PowerShell (Admin): wsl --shutdown  then reopen Docker Desktop" -ForegroundColor Yellow
exit 1
