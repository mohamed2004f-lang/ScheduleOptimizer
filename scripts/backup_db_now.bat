@echo off
setlocal
set ROOT=%~dp0..
python "%ROOT%\scripts\backup_db.py" --kind manual
if errorlevel 1 (
  echo Backup failed.
  exit /b 1
)
echo Backup completed.
endlocal
