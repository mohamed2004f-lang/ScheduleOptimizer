# نسخ PostgreSQL الاحتياطي — ScheduleOptimizer

## نسخ فوري (يدوي)

من جذر المشروع:

```powershell
cd C:\Users\BARCODE\ScheduleOptimizer
.\.venv\Scripts\python.exe scripts\pg_dump_via_env.py
```

الملف يُحفظ في `backups/pg_dump/` بصيغة `.dump` (استعادة عبر `pg_restore`).

نسخ SQL نصي:

```powershell
python scripts/pg_dump_via_env.py --format plain --out backups/pg_dump/manual.sql
```

## إعداد `pg_dump` على Windows

إذا ظهرت رسالة «لم يُعثر على pg_dump»:

### 1) إضافة إلى PATH (موصى به)

1. افتح **إعدادات النظام → متغيرات البيئة**.
2. أضف إلى `Path` مساراً مثل:
   `C:\Program Files\PostgreSQL\16\bin`
3. أعد فتح PowerShell وتحقق:

```powershell
pg_dump --version
```

### 2) أو عيّن مساراً صريحاً في `.env`

```env
PG_DUMP_PATH=C:\Program Files\PostgreSQL\16\bin\pg_dump.exe
```

## نسخ المرفقات

```powershell
Copy-Item -Recurse backend\uploads "backups\uploads_$(Get-Date -Format yyyyMMdd)"
```

## جدولة تلقائية (اختياري)

```powershell
scripts\setup_backup_tasks.bat
```

- يومي: 23:30 — `scripts\backup_db_daily.bat`
- أسبوعي (الأحد): 23:45 — `scripts\backup_db_weekly.bat`

## استعادة من `.dump`

```powershell
$env:PGPASSWORD = "your_password"
pg_restore -h localhost -p 5432 -U postgres -d schedule_optimizer --clean --if-exists backups\pg_dump\YYYYMMDD_HHMMSS_dbname.dump
```

**تحذير:** `--clean` يحذف الكائنات الحالية قبل الاستعادة — استخدمه على قاعدة اختبار أولاً.

## قبل التحديثات الكبيرة

1. `python scripts/pg_dump_via_env.py`
2. نسخ `backend/uploads`
3. راجع `docs/RUNBOOK.md` §4
