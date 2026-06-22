# Start Docker Desktop (if needed) and wait until the engine responds.
param(
    [int]$MaxWaitSeconds = 180
)

$ErrorActionPreference = "SilentlyContinue"

function Test-DockerEngine {
    $null = docker info 2>$null
    return $LASTEXITCODE -eq 0
}

if (Test-DockerEngine) {
    Write-Host "Docker engine: OK"
    exit 0
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
    Start-Sleep -Seconds 4
    if (Test-DockerEngine) {
        Write-Host "Docker engine ready."
        docker version --format "Server: {{.Server.Version}}"
        exit 0
    }
    Write-Host "Waiting for Docker engine..."
}

Write-Host "Docker engine did not become ready within ${MaxWaitSeconds}s." -ForegroundColor Red
Write-Host "Try: restart Docker Desktop from the tray icon, or run: wsl --shutdown then reopen Docker." -ForegroundColor Yellow
exit 1
