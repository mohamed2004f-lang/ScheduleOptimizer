@echo off
setlocal
set ROOT=%~dp0..
python "%ROOT%\scripts\pg_dump_via_env.py"
if errorlevel 1 (
  echo Backup failed.
  exit /b 1
)
echo Backup completed.
endlocal
