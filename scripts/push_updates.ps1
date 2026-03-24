param(
    [string]$Branch = "master"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== ScheduleOptimizer: Push Updates ===" -ForegroundColor Cyan
Write-Host ""

git rev-parse --is-inside-work-tree 1>$null 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Current folder is not a git repository." -ForegroundColor Red
    exit 1
}

Write-Host "Current status:" -ForegroundColor Yellow
git status --short --branch
Write-Host ""

$msg = Read-Host "Commit message (leave empty for default)"
if ([string]::IsNullOrWhiteSpace($msg)) {
    $msg = "Project updates"
}

$confirm = Read-Host "Continue with add/commit/push? Type y to continue"
$confirm = ($confirm | Out-String).Trim().ToLower()
if (($confirm -ne "y") -and ($confirm -ne "yes") -and ($confirm -ne "نعم")) {
    Write-Host "Canceled." -ForegroundColor Yellow
    exit 0
}

git add -A
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "No staged changes to commit." -ForegroundColor Yellow
    exit 0
}

git commit -m "$msg"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Commit failed." -ForegroundColor Red
    exit 1
}

git push origin $Branch
if ($LASTEXITCODE -ne 0) {
    Write-Host "Push failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Push completed successfully to origin/$Branch" -ForegroundColor Green
git status --short --branch
