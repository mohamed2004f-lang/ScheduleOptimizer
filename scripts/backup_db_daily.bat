@echo off
setlocal
set ROOT=%~dp0..
python "%ROOT%\scripts\backup_db.py" --kind daily
if errorlevel 1 exit /b 1
endlocal
