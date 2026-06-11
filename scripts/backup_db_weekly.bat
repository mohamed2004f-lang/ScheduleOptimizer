@echo off
setlocal
set ROOT=%~dp0..
python "%ROOT%\scripts\pg_dump_via_env.py"
if errorlevel 1 exit /b 1
endlocal
