@echo off
setlocal
echo ScheduleOptimizer: full backup to D: drive...
set ROOT=%~dp0..
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\backup_full_to_d.ps1"
if errorlevel 1 (
  echo Backup FAILED.
  pause
  exit /b 1
)
echo Backup completed. Check D:\ScheduleOptimizer_Backups
pause
endlocal
