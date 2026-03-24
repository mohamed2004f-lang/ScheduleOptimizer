@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\push_updates.ps1" -Branch "master"
echo.
echo Press any key to close this window...
pause > nul
endlocal
