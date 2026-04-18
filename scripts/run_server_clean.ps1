param(
  [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"

Set-Location -Path (Resolve-Path "$PSScriptRoot\..")

Write-Host "[run] Cleaning port 5000 listeners..." -ForegroundColor Cyan
$pids = @(
  netstat -ano |
    Select-String ":5000" |
    ForEach-Object { ($_ -split "\s+")[-1] } |
    Where-Object { $_ -match "^\d+$" } |
    Select-Object -Unique
)
foreach ($procId in $pids) {
  if ($procId -and $procId -ne 0) {
    try {
      Stop-Process -Id $procId -Force -ErrorAction Stop
      Write-Host "[kill] PID $procId" -ForegroundColor Yellow
    } catch {
      Write-Host "[skip] PID $procId" -ForegroundColor DarkYellow
    }
  }
}

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  throw "Python venv not found at $py"
}

Write-Host "[run] Starting app server..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $py -ArgumentList "app.py" -WorkingDirectory (Get-Location) -PassThru -WindowStyle Hidden

try {
  Start-Sleep -Seconds 3
  $ready = $false
  for ($i = 0; $i -lt 20; $i++) {
    try {
      $resp = Invoke-WebRequest -Uri "http://127.0.0.1:5000/auth/check" -UseBasicParsing -TimeoutSec 3
      if ($resp.StatusCode -eq 200) {
        $ready = $true
        break
      }
    } catch {
      Start-Sleep -Milliseconds 700
    }
  }
  if (-not $ready) {
    throw "Server did not become ready on :5000"
  }

  Write-Host "[run] Running head switch probe..." -ForegroundColor Cyan
  & $py "scripts/head_switch_probe.py"
  if ($LASTEXITCODE -ne 0) {
    throw "head_switch_probe failed with exit code $LASTEXITCODE"
  }
  Write-Host "[pass] Server + probe are healthy." -ForegroundColor Green
} finally {
  if (-not $KeepRunning -and $proc -and -not $proc.HasExited) {
    Write-Host "[run] Stopping test server PID $($proc.Id)" -ForegroundColor Cyan
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  } elseif ($KeepRunning -and $proc -and -not $proc.HasExited) {
    Write-Host "[pass] Server is left running on :5000 (PID $($proc.Id))." -ForegroundColor Green
  }
}
