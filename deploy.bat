@echo off
title ScheduleOptimizer Deploy
cd /d "%~dp0"

echo.
echo  ============================================
echo    ScheduleOptimizer - Deploy to Internet
echo  ============================================
echo.
echo  Wait 1-3 minutes. Do NOT close this window.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\deploy_production.ps1"
set DEPLOY_ERR=%ERRORLEVEL%

echo.
echo  --------------------------------------------
if %DEPLOY_ERR% neq 0 (
  echo  FAILED - read messages above.
  echo  If Docker is off: open Docker Desktop first.
) else (
  echo  SUCCESS
  echo  Open: https://uod-engineering.org
  echo  Then press Ctrl+F5 in the browser
)
echo  --------------------------------------------
echo.
echo  Press any key to close...
pause >nul
