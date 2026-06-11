# PostgreSQL — قاعدة البيانات الوحيدة

ScheduleOptimizer يعمل على **PostgreSQL** فقط (`DATABASE_URL` في `.env`).

## نسخ احتياطي

```powershell
python scripts/pg_dump_via_env.py
Copy-Item -Recurse backend\uploads "backups\uploads_$(Get-Date -Format yyyyMMdd)"
```

## مخطط قاعدة البيانات (Alembic)

```powershell
alembic upgrade head
```

راجع `docs/ALEMBIC.md`.

## التحقق من البيانات

```powershell
python scripts/_verify_pg_data.py
```
