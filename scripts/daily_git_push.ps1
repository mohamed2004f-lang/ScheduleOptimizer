#Requires -Version 5.1
param(
    [string]$Branch = "master",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$env:GIT_TERMINAL_PROMPT = "0"
$env:GCM_INTERACTIVE = "Never"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$LogDir = Join-Path $RepoRoot "logs"
$LogFile = Join-Path $LogDir "daily_git_push.log"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

function Write-Log([string]$Message, [string]$Level = "INFO") {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts][$Level] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    $color = switch ($Level) {
        "ERROR" { "Red" }
        "WARN"  { "Yellow" }
        "OK"    { "Green" }
        default { "Gray" }
    }
    Write-Host $line -ForegroundColor $color
}

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    # Git writes progress to stderr; do not treat that as a terminating error.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & git -C $RepoRoot @GitArgs 2>&1
        $code = [int]$LASTEXITCODE
        foreach ($line in @($output)) {
            if ($null -eq $line) { continue }
            if ($line -is [System.Management.Automation.ErrorRecord]) {
                Write-Host $line.ToString()
            } else {
                Write-Host $line
            }
        }
        return $code
    }
    finally {
        $ErrorActionPreference = $prev
    }
}

Write-Log "=== daily git push start (branch=$Branch dryRun=$DryRun) ==="

Push-Location $RepoRoot
try {
    $inside = & git rev-parse --is-inside-work-tree 2>$null
    if ($LASTEXITCODE -ne 0 -or "$inside".Trim() -ne "true") {
        Write-Log "Not a git repository: $RepoRoot" "ERROR"
        exit 1
    }

    $current = (& git rev-parse --abbrev-ref HEAD).Trim()
    if ($current -ne $Branch) {
        Write-Log "Current branch is '$current' (expected '$Branch'). Aborting." "ERROR"
        exit 2
    }

    Write-Log "pull --rebase --autostash origin/$Branch"
    $pullCode = Invoke-Git pull --rebase --autostash origin $Branch
    if ($pullCode -ne 0) {
        Write-Log "git pull --rebase failed (possible conflict). No force push." "ERROR"
        exit 3
    }

    $pathspecs = @(
        "."
        ":(exclude)backend/uploads"
        ":(exclude)backend/uploads/**"
        ":(exclude).env"
        ":(exclude).env.*"
        ":(exclude)**/.env"
        ":(exclude)**/.env.*"
        ":(exclude)credentials.json"
        ":(exclude)**/credentials.json"
        ":(exclude)**/*secret*"
        ":(exclude)**/*credentials*"
        ":(exclude).venv"
        ":(exclude).venv/**"
        ":(exclude)**/__pycache__"
        ":(exclude)**/*.pyc"
        ":(exclude)logs/*.log"
        ":(exclude)logs/*.log.*"
    )

    Write-Log "git add (code only; uploads/.env excluded)"
    $addArgs = @("-c", "advice.addIgnoredFile=false", "add", "-A", "--") + $pathspecs
    $addCode = Invoke-Git @addArgs
    if ($addCode -ne 0) {
        # Git may return non-zero with advisory messages; continue if index advanced.
        Write-Log "git add exit=$addCode (checking staged files)" "WARN"
    }

    & git -C $RepoRoot diff --cached --quiet
    $hasStaged = ($LASTEXITCODE -ne 0)

    if (-not $hasStaged) {
        Write-Log "No new staged changes to commit." "OK"
    }
    else {
        $dateStamp = Get-Date -Format "yyyy-MM-dd"
        # Arabic commit message: نسخة يومية تلقائية YYYY-MM-DD
        $msg = "نسخة يومية تلقائية $dateStamp"
        $summary = (& git -C $RepoRoot diff --cached --stat) | Out-String
        Write-Log ("Staged summary:`n" + $summary.Trim())

        if ($DryRun) {
            Write-Log "DryRun: skipping commit/push" "WARN"
            & git -C $RepoRoot reset HEAD --quiet 2>$null
            exit 0
        }

        Write-Log "Creating commit..."
        $commitCode = Invoke-Git commit -m $msg
        if ($commitCode -ne 0) {
            Write-Log "git commit failed" "ERROR"
            exit 5
        }
    }

    if ($DryRun) {
        Write-Log "DryRun: skipping push" "WARN"
        exit 0
    }

    Write-Log "git push origin/$Branch"
    $pushCode = Invoke-Git push origin $Branch
    if ($pushCode -ne 0) {
        Write-Log "git push failed" "ERROR"
        exit 6
    }

    Write-Log "Daily push completed successfully." "OK"
    exit 0
}
catch {
    Write-Log ("Exception: " + $_.Exception.Message) "ERROR"
    exit 99
}
finally {
    Pop-Location
}
