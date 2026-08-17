# Alembic وقاعدة البيانات

التشغيل على **PostgreSQL فقط**. المخطط يُطبَّق بـ Alembic وليس عند إقلاع Flask.

## المتغيرات

- **`DATABASE_URL`**: `postgresql+psycopg://USER:PASS@HOST:5432/DBNAME`
- **`ALLOW_ENSURE_TABLES=1`**: طوارئ فقط — يعيد سلوك `ensure_tables` القديم إن غاب `alembic_version`

## قبل تشغيل التطبيق محلياً

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

ثم شغّل التطبيق كالعادة. Docker ينفّذ `alembic upgrade head` تلقائياً قبل gunicorn.

## الأوامر

```bash
alembic upgrade head
alembic current
alembic revision -m "describe change"
```

### Windows

لا تستخدم `python -m alembic` من جذر المشروع (المجلد `alembic/` يحجب الحزمة). استخدم:

```powershell
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\alembic.exe upgrade head
```

## الترحيلات

| الإصدار | الغرض |
|---|---|
| `0001_baseline` | إنشاء الجداول الأساسية (PostgreSQL) |
| `0002_pg_parity` | ترقيات كانت تُطبَّق عند الإقلاع (أعمدة TOTP، مجموعات تدريس، …) — idempotent |
| `0003_invite_hash` | `survey_invites.token_hash` — تخزين بصمة الرابط لا الرمز الخام |
| `0004_term_engine` | محرّك الفصل موجة 0: `term_master`، `term_windows`، `academic_calendar_versions` |
| `0005_term_ops` | موجات 2–4: `grace_until`، `registrations.semester`، أرشيف السلة، سجل التعديل، استثناءات |
| `0006_spring_new` | تقويم الربيع: بند تسجيل المستجدين (رقم 2) مع إزاحة البنود التالية |
| `0007_cal_start` | `academic_calendar.event_date_start` — بداية النافذة للبنود ذات المدة |
| `0008_term_offer` | عرض مقررات الفصل: `term_course_offerings` + `term_offering_state` |
| `0009_dept_offer` | عرض لكل قسم: `UNIQUE(term_key, course_name, department_id)` وحالة اعتماد لكل قسم |
| `0010_reg_sem_uq` | سلة متعددة الفصول: `UNIQUE(student_id, course_name, semester)` |

قاعدة قديمة بلا `alembic_version`: `alembic upgrade head` آمن لأن الجمل `IF NOT EXISTS`.

## الاختبارات

pytest ما زال يستخدم SQLite في الذاكرة عبر `conftest` ولا يشغّل Alembic.

تقسيم وحدات `backend/database/` موثَّق في [ARCHITECTURE.md](ARCHITECTURE.md).
