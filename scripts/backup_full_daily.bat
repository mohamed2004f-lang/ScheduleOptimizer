@echo off
setlocal
set ROOT=%~dp0..
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\backup_full_to_d.ps1"
if errorlevel 1 exit /b 1
endlocal
