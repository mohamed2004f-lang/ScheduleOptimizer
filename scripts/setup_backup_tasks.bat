@echo off
setlocal
set ROOT=%~dp0..
set DAILY_CMD="%ROOT%\scripts\backup_full_daily.bat"
set WEEKLY_CMD="%ROOT%\scripts\backup_full_daily.bat"

echo Creating/Updating scheduled backup tasks...
echo Target: BACKUP_MIRROR_ROOT in .env  ^(default D:\ScheduleOptimizer_Backups^)
echo.

schtasks /create /f /sc daily /tn "ScheduleOptimizer_DB_Backup_Daily" /tr %DAILY_CMD% /st 23:30
if errorlevel 1 (
  echo Failed to create daily task. Run this script as the Windows user that owns the Docker/project files.
  exit /b 1
)

schtasks /create /f /sc weekly /d SUN /tn "ScheduleOptimizer_DB_Backup_Weekly" /tr %WEEKLY_CMD% /st 23:45
if errorlevel 1 (
  echo Failed to create weekly task.
  exit /b 1
)

echo.
echo Done.
echo Daily:  23:30  ^(PostgreSQL .dump + uploads^)
echo Weekly: Sunday 23:45
echo Verify:  powershell -File "%ROOT%\scripts\verify_daily_backup.ps1"
echo Manual:  "%ROOT%\scripts\backup_full_now.bat"
endlocal
