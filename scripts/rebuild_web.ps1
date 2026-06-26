# Rebuild web container only — shows full build progress (use if deploy seems stuck).
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "=== Rebuild web (plain progress) ===" -ForegroundColor Cyan
$env:DOCKER_BUILDKIT = "1"
$env:COMPOSE_PROGRESS = "plain"

docker compose build --progress=plain web
if ($LASTEXITCODE -ne 0) { exit 1 }

docker compose up -d web
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host ""
Write-Host "Done. Check: docker compose ps" -ForegroundColor Green
docker compose exec web pg_dump --version 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "pg_dump in container: OK" -ForegroundColor Green
} else {
    Write-Host "pg_dump check failed - run: docker compose exec web pg_dump --version" -ForegroundColor Yellow
}
