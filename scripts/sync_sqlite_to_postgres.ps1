#Requires -Version 5.1
<#
.SYNOPSIS
  نسخ احتياطي لـ SQLite ثم نقل كامل إلى PostgreSQL (TRUNCATE + إدراج).

.DESCRIPTION
  1) python scripts/backup_db.py --kind manual
  2) python scripts/migrate_sqlite_to_postgres.py --truncate --yes

  يتطلب في .env: DATABASE_URL=postgresql+psycopg://...
  أمان: لا ترفع .env إلى Git (.env مُستبعد في .gitignore).

.NOTES
  تغيير كلمة مرور postgres: نفّذها في الخادم (pgAdmin أو psql) ثم حدّث DATABASE_URL في .env.
  المرحلة 4 (Flask على Postgres): لم تُنفَّذ بعد؛ Flask ما زال يقرأ SQLite من DATABASE_PATH.
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "== [1/2] نسخ احتياطي لـ mechanical.db ==" -ForegroundColor Cyan
python scripts/backup_db.py --kind manual
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== [2/2] نقل SQLite -> Postgres (truncate) ==" -ForegroundColor Cyan
python scripts/migrate_sqlite_to_postgres.py --truncate --yes
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "تم." -ForegroundColor Green
