$ErrorActionPreference = 'SilentlyContinue'
$pids = @(
    Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
)
if (-not $pids) {
    Write-Host 'No listener on port 5000'
    exit 0
}
foreach ($procId in $pids) {
    if ($procId) {
        Stop-Process -Id $procId -Force
        Write-Host ('Stopped PID ' + $procId)
    }
}
