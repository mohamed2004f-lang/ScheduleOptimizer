@echo off
setlocal
set ROOT=%~dp0..
for %%I in ("%ROOT%") do set ROOT=%%~fI
set SCRIPT=%ROOT%\scripts\daily_git_push.ps1
set TASK=ScheduleOptimizer_GitHub_Daily
set TIME=23:00

echo Creating/Updating scheduled task: %TASK%
echo Runs daily at %TIME% (when this Windows user is logged on).
echo Script: %SCRIPT%

schtasks /create /f /sc daily /tn "%TASK%" /st %TIME% /rl LIMITED ^
  /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%SCRIPT%\""
if errorlevel 1 (
  echo Failed to create scheduled task.
  exit /b 1
)

echo.
echo Done.
echo Task: %TASK%
echo Time: daily %TIME%
echo Log:  %ROOT%\logs\daily_git_push.log
echo.
echo Test now:
echo   powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -DryRun
endlocal
