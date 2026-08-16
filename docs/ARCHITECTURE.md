"""عمارة الربع السنوي — تقسيم الطبقات

صيانة هندسية **بدون تغيير شاشات المستخدم**. الهدف: ملفات أصغر، مصدر واحد للمخطط، ومستودعات للاستعلامات الساخنة.

## المبدأ

الاستيرادات القديمة تبقى صالحة. التقسيم داخلي؛ الواجهة العامة ثابتة.

| الواجهة القديمة | التنفيذ بعد التقسيم |
|---|---|
| `from backend.database.database import get_connection, TABLES_SCHEMA, …` | `database.py` يعيد التصدير من وحدات شقيقة |
| `from backend.core.auth import role_required, _normalize_role, compute_capabilities, …` | `auth.py` يعيد التصدير من وحدات `auth_*` |
| `from backend.services.schedule import _assigned_section_rows` | يغلف `backend.repositories.schedule_repo` |

لا تُحوَّل `auth.py` أو `schedule.py` إلى حزمة (`auth/` أو `schedule/`) ما دام الملف `.py` موجوداً: على Windows يتعارض المساران، وأكثر من مئتي مستورد يعتمد على `backend.core.auth`.

## قاعدة البيانات (`backend/database/`)

| ملف | مسؤولية |
|---|---|
| `db_config.py` | `DATABASE_URL`، `is_postgresql`، `require_postgres_url` |
| `connection.py` | `get_connection`، التجمع، `db_transaction` |
| `pg_compat.py` | محوّل PostgreSQL ↔ واجهة sqlite3 |
| `introspection.py` | `table_exists`، `fetch_table_columns`، `schedule_pk_column` — يعتمد على **الاتصال الفعلي** لا على عنوان URL |
| `schema_ddl.py` | `TABLES_SCHEMA` + `INDEXES` (مصدر Alembic 0001) |
| `schema_guard.py` | `assert_schema_ready`، `ensure_tables` (طوارئ/اختبار) |
| `migrations_postgresql.py` | ترقيات توافقية / Alembic 0002 |
| `migrations_sqlite.py` | مخطط SQLite للاختبارات فقط |
| `backfills.py` | ترحيل بيانات توافقية |
| `helpers.py` | `validate_table_name`، `table_to_dicts` |
| `database.py` | واجهة توافق فقط |
| `pg_sql.py` / `pg_convert.py` | مؤرشفان ومعطّلان — لا يُستوردان وقت التشغيل |

Alembic `env.py` يستورد `require_postgres_url` من `db_config` حتى لا يُحمَّل تجمع الاتصالات عند الترحيل.

pytest يستخدم SQLite في الذاكرة. `table_exists` ورفاقه يفحصون نوع الاتصال (`conn_is_postgresql`) حتى لا تُنفَّذ جمل PostgreSQL على SQLite عندما يكون `.env` مضبوطاً على Postgres.

## المصادقة (`backend/core/`)

| ملف | مسؤولية |
|---|---|
| `auth_constants.py` | مفاتيح الجلسة وأدوار النطاق |
| `auth_roles.py` | `_normalize_role` |
| `auth_password.py` | `hash_password` / `verify_password` |
| `auth_guards.py` | حراسة مسارات الطالب/الأستاذ |
| `auth_session.py` | أوضاع الجلسة ونطاق القسم |
| `auth_capabilities.py` | `compute_capabilities` (يستورد `permissions` عند الاستدعاء) |
| `auth.py` | `init_auth`، المزخرفات، إكمال الجلسة، إعادة التصدير |

`permissions.py` و`department_scope_policy.py` يستمران في الاستيراد من `backend.core.auth` كما كان. دوال القدرات تستورد `permissions` داخل الدالة لتفادي دورة الاستيراد.

## الجدول والمستودعات

`backend/repositories/schedule_repo.py`:

- شعب الأستاذ (`fetch_assigned_section_rows`) ودمج المقرر.
- قائمة الجدول مع عدد المسجّلين (`fetch_schedule_rows_with_student_counts`) — مسار HTTP في `schedule.py` ومسار `ScheduleService`.
- عدّ المسجّلين حسب المقرر (`count_students_grouped_by_course` / `count_distinct_students_for_courses`).

مستودعات قائمة مسبقاً: `users_repo`، `students_repo`، `instructors_repo`، `courses_repo`، `course_equivalence_repo`، `instructor_assignments_repo`، `instructor_students_repo`.

`users_repo.fetch_user_session_row` / `fetch_user_login_row`: قراءة المستخدم عند كل طلب ودخول.

مسارات HTTP في `schedule.py` لم تُقسَّم إلى حزمة؛ الخطوة التالية الآمنة بعد استقرار المستودع.

## الاختبارات

- `tests/test_quarterly_architecture.py` — سطح الاستيراد وإعادة التصدير.
- `tests/repositories/` — المستودعات على اتصال SQLite المشترك (`db_conn` يعتمد على تهيئة القاعدة المشتركة).

## ما لا يغيّره هذا الربع

- سلوك الدخول، الدرجات، الجدولة، أو الصلاحيات للمستخدم.
- لهجة التشغيل: PostgreSQL في الإنتاج؛ SQLite في pytest فقط.
- شكل الاستيراد في الخدمات الحالية.
