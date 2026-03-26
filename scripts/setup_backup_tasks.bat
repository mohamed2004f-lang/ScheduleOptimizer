@echo off
setlocal
set ROOT=%~dp0..
set DAILY_CMD="%ROOT%\scripts\backup_db_daily.bat"
set WEEKLY_CMD="%ROOT%\scripts\backup_db_weekly.bat"

echo Creating/Updating scheduled tasks...
schtasks /create /f /sc daily /tn "ScheduleOptimizer_DB_Backup_Daily" /tr %DAILY_CMD% /st 23:30 >nul
if errorlevel 1 (
  echo Failed to create daily task.
  exit /b 1
)

schtasks /create /f /sc weekly /d SUN /tn "ScheduleOptimizer_DB_Backup_Weekly" /tr %WEEKLY_CMD% /st 23:45 >nul
if errorlevel 1 (
  echo Failed to create weekly task.
  exit /b 1
)

echo Done.
echo Daily:  23:30
echo Weekly: Sunday 23:45
endlocal
