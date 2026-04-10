# الانتقال إلى PostgreSQL — خطة مراحل آمنة

## الحالة الحالية

- **التطبيق (Flask)** يعتمد على `sqlite3` واستعلامات خاصة بـ SQLite (`?`، `INSERT OR REPLACE`، `sqlite_master`، `PRAGMA`).
- **Alembic** يمكنه إنشاء المخطط على PostgreSQL (انظر `docs/ALEMBIC.md`).
- **المرحلة 3 (نقل البيانات):** يوجد سكربت جاهز: `scripts/migrate_sqlite_to_postgres.py`.
- **تم تنفيذ المرحلة 1** (بيانات): سكربت `scripts/fix_duplicate_course_codes.py` لإصلاح تكرار `course_code` قبل الفهارس الفريدة.

## المراحل

### المرحلة 1 — جودة البيانات على SQLite (منجزة)

1. تشغيل معاينة: `python scripts/fix_duplicate_course_codes.py`
2. تطبيق مع نسخة احتياطية: `python scripts/fix_duplicate_course_codes.py --apply`
3. التحقق: إعادة تشغيل التطبيق وتأكد من اختفاء تحذير الفهرس الفريد على `courses(course_code)`.

### المرحلة 2 — قاعدة PostgreSQL فارغة + Alembic

1. تثبيت خادم PostgreSQL وإنشاء قاعدة (مثلاً `schedule_optimizer`).
2. **نسخة احتياطية** من `backend/database/mechanical.db` (نسخ الملف إلى مجلد `backups/`).
3. في `.env` عيّن مؤقتاً:
   ```env
   DATABASE_URL=postgresql+psycopg://USER:PASS@localhost:5432/schedule_optimizer
   ```
4. من جذر المشروع:
   ```bash
   alembic upgrade head
   ```
5. تحقق في pgAdmin أو `psql` أن الجداول أُنشئت في `public`.

### المرحلة 3 — نقل البيانات (سكربت المشروع)

1. اترك `DATABASE_URL` يشير إلى **نفس** قاعدة Postgres بعد `alembic upgrade head`.
2. (اختياري) مصدر SQLite مختلف عن الافتراضي:
   ```env
   SQLITE_MIGRATION_SOURCE=C:\مسار\كامل\mechanical.db
   ```
3. **معاينة** (أعداد الصفوف من SQLite، وعرض وجهة Postgres إن وُجدت):
   ```bash
   python scripts/migrate_sqlite_to_postgres.py --dry-run
   ```
4. **التنفيذ** — يفرّغ جداول التطبيق على Postgres ثم ينسخ الصفوف (مدمّر لبيانات Postgres الحالية في تلك الجداول):
   ```bash
   python scripts/migrate_sqlite_to_postgres.py --truncate --yes
   ```
5. راجع في pgAdmin أعداد الصفوف مقارنة بمعاينة `--dry-run`.

**ملاحظات:**

- السكربت يستخدم `TRUNCATE ... RESTART IDENTITY CASCADE` على جميع جداول `TABLES_SCHEMA`؛ لا يُشغَّل على قاعدة إنتاج تحتوي بياناتاً تريد الإبقاء عليها دون نسخ احتياطي.
- إن فشل `SET session_replication_role = replica`، قد تحتاج اتصالاً بمستخدم سوبرمستخدم؛ السكربت يتابع مع طباعة تنبيه.

### المرحلة 4 — تشغيل التطبيق على PostgreSQL (لم تكتمل بعد)

يتطلب على الأقل:

- طبقة اتصال موحّدة (مثل SQLAlchemy أو `psycopg`) بدل `sqlite3` المباشر.
- استبدال أو تحويل: `INSERT OR REPLACE` / `INSERT OR IGNORE`، واستعلامات `sqlite_master` و`PRAGMA`.
- تعديل `df_from_query` وغيرها في `utilities.py` التي تفتح SQLite مباشرة.

**حتى اكتمال المرحلة 4:** يمكن الإبقاء على `DATABASE_URL` لـ **Postgres** في `.env`؛ **Flask** يتصل تلقائياً بملف **SQLite** المحدَّد في `DATABASE_PATH` (انظر `get_connection` في `database.py`). استخدم عنوان Postgres لـ **Alembic** وسكربت **migrate_sqlite_to_postgres**.

## متغيرات مفيدة

| المتغير | الغرض |
|---------|--------|
| `DATABASE_URL` | عنوان SQLAlchemy (SQLite أو Postgres). |
| `DATABASE_PATH` | مسار ملف SQLite عند عدم استخدام `DATABASE_URL` الكامل. |
| `SQLITE_MIGRATION_SOURCE` | مسار ملف `.db` المصدر لسكربت النقل (اختياري). |

## أدوات جاهزة (بعد النقل)

| الغرض | الأمر |
|--------|--------|
| مزامنة دورية SQLite → Postgres (نسخ احتياطي ثم truncate + نقل) | من PowerShell في جذر المشروع: `.\scripts\sync_sqlite_to_postgres.ps1` |
| `pg_dump` باستخدام `DATABASE_URL` من `.env` | `python scripts/pg_dump_via_env.py` (يتطلب `pg_dump` في PATH) |
| تشغيل أقرب للإنتاج على ويندوز | `pip install -r requirements-production.txt` ثم `python scripts/run_waitress.py` |

**تغيير كلمة مرور `postgres`:** نفّذها في الخادم (pgAdmin → Definition → Password، أو `ALTER USER postgres PASSWORD '...';` في psql) ثم حدّث `DATABASE_URL` في `.env`. تغيير `.env` وحده لا يكفي.

## ملاحظة أمان

قبل أي قطع على الإنتاج: نسخة احتياطية كاملة من `mechanical.db`، ونافذة صيانة، وخطة تراجع (إعادة الملف أو استعادة Postgres من `pg_dump`). لا ترفع `.env` إلى Git (مُدرَج في `.gitignore`).
