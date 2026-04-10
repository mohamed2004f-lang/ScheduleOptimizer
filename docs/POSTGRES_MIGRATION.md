# الانتقال إلى PostgreSQL — خطة مراحل آمنة

## الحالة الحالية

- **التطبيق (Flask)** يعتمد على `sqlite3` واستعلامات خاصة بـ SQLite (`?`، `INSERT OR REPLACE`، `sqlite_master`، `PRAGMA`).
- **Alembic** يمكنه إنشاء المخطط على PostgreSQL (انظر `docs/ALEMBIC.md`).
- **تم تنفيذ المرحلة 1** (بيانات): سكربت `scripts/fix_duplicate_course_codes.py` لإصلاح تكرار `course_code` قبل الفهارس الفريدة.

## المراحل

### المرحلة 1 — جودة البيانات على SQLite (منجزة)

1. تشغيل معاينة: `python scripts/fix_duplicate_course_codes.py`
2. تطبيق مع نسخة احتياطية: `python scripts/fix_duplicate_course_codes.py --apply`
3. التحقق: إعادة تشغيل التطبيق وتأكد من اختفاء تحذير الفهرس الفريد على `courses(course_code)`.

### المرحلة 2 — قاعدة PostgreSQL فارغة + Alembic

1. تثبيت خادم PostgreSQL وإنشاء مستخدم وقاعدة بيانات.
2. ضبط `DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:5432/DBNAME` في بيئة **staging** فقط.
3. `alembic upgrade head`
4. مقارنة الجداول مع SQLite (عدد الجداول، فحص عيّنة).

### المرحلة 3 — نقل البيانات

- سكربت مخصص أو `pgloader` من SQLite إلى Postgres، جدولاً جدولاً بترتيب المفاتيح الأجنبية.
- فحوص: عدد الصفوف لكل جدول، عيّنة من السجلات الحرجة.

### المرحلة 4 — تشغيل التطبيق على PostgreSQL (لم تكتمل بعد)

يتطلب على الأقل:

- طبقة اتصال موحّدة (مثل SQLAlchemy أو `psycopg`) بدل `sqlite3` المباشر.
- استبدال أو تحويل: `INSERT OR REPLACE` / `INSERT OR IGNORE`، واستعلامات `sqlite_master` و`PRAGMA`.
- تعديل `df_from_query` وغيرها في `utilities.py` التي تفتح SQLite مباشرة.

**حتى اكتمال المرحلة 4:** اجعل `DATABASE_URL` يشير إلى **SQLite** لتشغيل التطبيق (`sqlite:///...` أو الاعتماد على `DATABASE_PATH` في `config.py`).

## متغيرات مفيدة

| المتغير | الغرض |
|---------|--------|
| `DATABASE_URL` | عنوان SQLAlchemy (SQLite أو Postgres). |
| `DATABASE_PATH` | مسار ملف SQLite عند عدم استخدام `DATABASE_URL` الكامل. |

## ملاحظة أمان

قبل أي قطع على الإنتاج: نسخة احتياطية كاملة من `mechanical.db`، ونافذة صيانة، وخطة تراجع (إعادة الملف أو استعادة Postgres من `pg_dump`).
