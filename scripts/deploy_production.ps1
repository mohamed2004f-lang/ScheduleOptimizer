# Deploy to production (Docker) -> uod-engineering.org
param(
    [switch]$SkipBuild,
    [switch]$WebOnly
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$LogFile = Join-Path $Root "logs\deploy.log"

function Write-Step($n, $msg) {
    $line = "[$n] $msg"
    Write-Host $line -ForegroundColor Yellow
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null
        Add-Content -Path $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $line"
    } catch { }
}

function Invoke-DockerCompose {
    param([switch]$Build, [switch]$WebOnly)
    $env:DOCKER_BUILDKIT = "1"
    $env:COMPOSE_PROGRESS = "plain"
    if ($Build) {
        Write-Host "     --- docker compose build (plain progress) ---" -ForegroundColor DarkGray
        if ($WebOnly) {
            docker compose build --progress=plain web
        } else {
            docker compose build --progress=plain
        }
        if ($LASTEXITCODE -ne 0) { return $LASTEXITCODE }
        Write-Host "     --- docker compose up -d ---" -ForegroundColor DarkGray
        if ($WebOnly) {
            docker compose up -d web
        } else {
            docker compose up -d
        }
    } else {
        if ($WebOnly) {
            docker compose up -d web
        } else {
            docker compose up -d
        }
    }
    return $LASTEXITCODE
}

Write-Host ""
Write-Host "=== ScheduleOptimizer: Deploy ===" -ForegroundColor Cyan
Write-Host ""

Write-Step "1/5" "Ensuring Docker engine..."
& (Join-Path $Root "scripts\docker_ensure.ps1")
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host "     Docker: OK" -ForegroundColor Green

Write-Step "2/5" "Freeing port 5000 (local app.py only, not Docker)..."
& (Join-Path $Root "scripts\stop_port_5000.ps1") | Out-Null

Write-Step "3/5" "Checking Cloudflare Tunnel..."
$cf = Get-Service -Name Cloudflared -ErrorAction SilentlyContinue
if ($null -eq $cf) {
    Write-Host "     Warning: Cloudflared service not found" -ForegroundColor Yellow
} elseif ($cf.Status -ne "Running") {
    Write-Host "     Starting Cloudflared..." -ForegroundColor Yellow
    try {
        Start-Service Cloudflared -ErrorAction Stop
        Write-Host "     Cloudflared: OK" -ForegroundColor Green
    } catch {
        Write-Host "     Could not start Cloudflared (try Run as Administrator)" -ForegroundColor Red
    }
} else {
    Write-Host "     Cloudflared: OK" -ForegroundColor Green
}

$target = if ($WebOnly) { "web container only" } else { "all containers" }
Write-Step "4/5" "Building and restarting $target (wait 1-3 min)..."

$composeOk = $false
for ($attempt = 1; $attempt -le 3; $attempt++) {
    if ($attempt -gt 1) {
        Write-Host "     docker compose failed - retry $attempt/3 after Docker re-check..." -ForegroundColor Yellow
        Start-Sleep -Seconds 8
        & (Join-Path $Root "scripts\docker_ensure.ps1") -MaxWaitSeconds 120 -WaitOnly | Out-Null
        if ($LASTEXITCODE -ne 0) { break }
    }
    $code = Invoke-DockerCompose -Build:(-not $SkipBuild) -WebOnly:$WebOnly
    if ($code -eq 0) {
        $composeOk = $true
        break
    }
}

if (-not $composeOk) {
    Write-Host ""
    Write-Host "docker compose FAILED." -ForegroundColor Red
    Write-Host "Docker engine may have stopped. Open Docker Desktop, wait for Engine running, then retry:" -ForegroundColor Yellow
    if ($WebOnly) {
        Write-Host "  docker compose up -d --build web" -ForegroundColor Yellow
    } else {
        Write-Host "  docker compose up -d --build" -ForegroundColor Yellow
    }
    exit 1
}
Write-Host "     Containers: OK" -ForegroundColor Green

Write-Step "5/5" "Health check..."
Start-Sleep -Seconds 8

$localOk = $false
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:5000/health" -UseBasicParsing -TimeoutSec 20
    if ($r.StatusCode -eq 200) { $localOk = $true }
} catch { }

if ($localOk) {
    Write-Host "     Local (127.0.0.1): OK" -ForegroundColor Green
} else {
    Write-Host "     Local: FAILED - run: docker compose logs web --tail 40" -ForegroundColor Red
}

$publicOk = $false
try {
    $r2 = Invoke-WebRequest -Uri "https://uod-engineering.org/health" -UseBasicParsing -TimeoutSec 25
    if ($r2.StatusCode -eq 200) { $publicOk = $true }
} catch { }

if ($publicOk) {
    Write-Host "     Internet: OK  https://uod-engineering.org" -ForegroundColor Green
} else {
    Write-Host "     Internet: not reachable - check Tunnel or network" -ForegroundColor Yellow
}

Write-Host ""
docker compose ps
Write-Host ""

if (-not $localOk) { exit 1 }
exit 0
