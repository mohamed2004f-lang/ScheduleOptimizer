# المرحلة 2 (المتوسطة) — ملخص التغييرات

**التاريخ:** 2026-04-13  
**المشروع:** ScheduleOptimizer  
**المرجع:** review_report.md — المرحلة 2 (المتوسطة)

---

## نظرة عامة

تم تنفيذ 3 مهام رئيسية لتحسين أداء المشروع وجودته:

| المهمة | الوصف | الملفات المعدّلة |
|--------|-------|-----------------|
| المهمة 1 | حل مشكلة N+1 Queries | `grades.py`, `performance.py` |
| المهمة 2 | إضافة اختبارات (Tests) | `conftest.py`, `test_routes.py`, `test_bulk_transcript.py` |
| المهمة 3 | إضافة Connection Pooling | `database.py`, `config.py`, `app.py` |

---

## المهمة 1: حل مشكلة N+1 Queries

### المشكلة

في ملف `backend/services/performance.py`، الدالتان `_build_performance_export_rows()` و `performance_report()` كانتا تقومان بحلقة `for` على كل طالب وتستدعيان `_load_transcript_data(sid)` لكل طالب على حدة. هذا يعني أن 500 طالب = 500+ استعلام إضافي لقاعدة البيانات.

### الحل

**1. إضافة دالة `_load_all_transcripts_bulk()` في `grades.py`** (بعد دالة `_load_transcript_data` مباشرة):

الدالة الجديدة تقوم بـ:
- جلب بيانات جميع الطلاب دفعة واحدة من جدول `students` باستعلام واحد.
- جلب جميع الدرجات دفعة واحدة من جدول `grades` باستعلام واحد.
- بناء بنية البيانات (transcript, semester_gpas, cumulative_gpa, completed_units) لكل طالب في الذاكرة.
- إرجاع `dict[str, dict]` حيث المفتاح هو `student_id`.
- تدعم تمرير قائمة `student_ids` اختيارية لتصفية الطلاب، أو `None` لجلب الجميع.
- قائمة فارغة `[]` ترجع dict فارغ (بدون استعلامات).

**2. تعديل `performance.py`:**

- تم استيراد `_load_all_transcripts_bulk` من `grades.py`.
- تم تعديل `_build_performance_export_rows()` لاستخدام `_load_all_transcripts_bulk()` بدلاً من حلقة فردية.
- تم تعديل `performance_report()` لاستخدام `_load_all_transcripts_bulk()` بدلاً من حلقة فردية.

### التأثير على الأداء

| المقياس | قبل | بعد |
|---------|-----|-----|
| عدد استعلامات الدرجات (500 طالب) | ~500 استعلام | 2 استعلام |
| نمط الاستعلام | O(n) — استعلام لكل طالب | O(1) — استعلام واحد bulk |

### الملفات المعدّلة

| الملف | التغيير |
|-------|---------|
| `backend/services/grades.py` | إضافة دالة `_load_all_transcripts_bulk()` (~120 سطر) |
| `backend/services/performance.py` | تعديل الاستيراد + تعديل `_build_performance_export_rows()` + تعديل `performance_report()` |

---

## المهمة 2: إضافة اختبارات (Tests)

### الملفات الجديدة

**1. `tests/conftest.py`** — ملف الإعدادات المشتركة للاختبارات:

- إنشاء قاعدة بيانات SQLite في الذاكرة (`:memory:`) مع جميع الجداول المطلوبة.
- إضافة بيانات تجريبية (طلاب، مقررات، درجات، مستخدم admin).
- Monkey-patching لـ `get_connection()` في جميع الوحدات (modules) لاستخدام قاعدة البيانات التجريبية.
- Fixtures مشتركة: `app`, `client`, `auth_client`, `db_conn`.

**2. `tests/test_routes.py`** — اختبارات Integration لمسارات Flask (12 اختبار):

| الفئة | الاختبارات | الوصف |
|-------|-----------|-------|
| `TestPublicRoutes` | 2 | `/health` و `/login` |
| `TestProtectedRoutesUnauthenticated` | 2 | `/` و `/dashboard` بدون تسجيل دخول |
| `TestAuthFlow` | 6 | تسجيل دخول/خروج، بيانات خاطئة، `/auth/check` |
| `TestProtectedRoutesAuthenticated` | 2 | `/` و `/students/list` بعد تسجيل الدخول |

**3. `tests/test_bulk_transcript.py`** — اختبارات Unit لدالة `_load_all_transcripts_bulk` (11 اختبار):

| الاختبار | الوصف |
|---------|-------|
| `test_bulk_returns_dict` | التحقق من نوع الإرجاع |
| `test_bulk_contains_seeded_students` | التحقق من وجود الطلاب |
| `test_bulk_student_has_expected_keys` | التحقق من المفاتيح المتوقعة |
| `test_bulk_gpa_calculation` | حساب المعدل التراكمي |
| `test_bulk_completed_units` | حساب الوحدات المنجزة |
| `test_bulk_failed_student_completed_units` | الطالب الراسب |
| `test_bulk_empty_list` | قائمة فارغة |
| `test_bulk_nonexistent_student` | طالب غير موجود |
| `test_bulk_matches_single_load` | مطابقة مع `_load_transcript_data` |
| `test_bulk_semester_gpas` | معدلات الفصول |
| `test_bulk_all_students_no_filter` | جلب الجميع بدون فلتر |

### نتائج التشغيل

| المجموعة | الإجمالي | ناجح | فاشل | ملاحظات |
|----------|---------|------|------|---------|
| الاختبارات الجديدة | 23 | 23 | 0 | جميعها ناجحة |
| الاختبارات القديمة | 19 | 15 | 4 | الفشل في اختبارات قديمة مكتوبة بشكل خاطئ (ليست مرتبطة بتعديلاتنا) |
| **المجموع** | **42** | **38** | **4** | |

> **ملاحظة:** الاختبارات الـ 4 الفاشلة هي اختبارات قديمة كانت مكتوبة بشكل خاطئ قبل تعديلاتنا:
> - `test_hash_password`: يفترض أن `hash_password` deterministic وهو ليس كذلك مع Werkzeug (salted hash).
> - `test_app_exception_default` / `test_app_exception_custom`: تغيّر `to_dict()` في `exceptions.py` (أضيف حقل `code`).
> - `test_normalize_sid`: دالة `normalize_sid` غير موجودة أصلاً في `StudentService`.

---

## المهمة 3: إضافة Connection Pooling

### المشكلة

في `database.py`، دالة `get_connection()` كانت تنشئ اتصال PostgreSQL جديد عبر `psycopg.connect()` في كل استدعاء. هذا غير فعال لأن إنشاء اتصال TCP جديد مكلف.

### الحل

**1. إضافة إعدادات Pool في `config.py`:**

```python
PG_POOL_MIN_SIZE = int(os.environ.get('PG_POOL_MIN_SIZE', '2'))
PG_POOL_MAX_SIZE = int(os.environ.get('PG_POOL_MAX_SIZE', '10'))
```

**2. تعديل `database.py`:**

- إضافة استيراد `PG_POOL_MIN_SIZE` و `PG_POOL_MAX_SIZE` من `config.py`.
- إضافة متغير عام `_pg_pool = None`.
- إضافة دالة `_get_or_create_pool()` التي تنشئ `psycopg_pool.ConnectionPool` عند أول استدعاء (lazy initialization).
- تعديل `_PgConnectionWrapper.__init__()` لقبول معامل `pool` اختياري.
- تعديل `_PgConnectionWrapper.close()` لإعادة الاتصال للـ pool (`pool.putconn()`) بدلاً من إغلاقه.
- تعديل `_PgConnectionWrapper.__exit__()` لاستدعاء `self.close()` بدلاً من `self._conn.close()`.
- تعديل `get_connection()` لأخذ اتصال من الـ pool عبر `pool.getconn()`.
- إضافة دالة `close_pool()` لإغلاق الـ pool عند إيقاف التطبيق.
- **Graceful fallback:** إذا لم تكن مكتبة `psycopg_pool` مثبتة، يتم إنشاء اتصال مباشر كما كان سابقاً (مع تحذير في الـ log).

**3. تعديل `app.py`:**

- استيراد `close_pool` من `database.py`.
- تسجيل `close_pool` عبر `atexit.register(close_pool)` لضمان إغلاق الـ pool عند إيقاف التطبيق.

### التأثير

| المقياس | قبل | بعد |
|---------|-----|-----|
| إنشاء اتصال PostgreSQL | جديد لكل طلب | من pool (إعادة استخدام) |
| الحد الأدنى للاتصالات | — | 2 (قابل للتعديل عبر `PG_POOL_MIN_SIZE`) |
| الحد الأقصى للاتصالات | غير محدود | 10 (قابل للتعديل عبر `PG_POOL_MAX_SIZE`) |
| سلوك SQLite | بدون تغيير | بدون تغيير |
| إغلاق الـ pool | — | تلقائي عبر `atexit` |

### الملفات المعدّلة

| الملف | التغيير |
|-------|---------|
| `config.py` | إضافة `PG_POOL_MIN_SIZE` و `PG_POOL_MAX_SIZE` |
| `backend/database/database.py` | إضافة pool logic + تعديل `_PgConnectionWrapper` + تعديل `get_connection()` + إضافة `close_pool()` |
| `app.py` | استيراد `close_pool` + تسجيل `atexit` |

---

## النسخ الاحتياطية

تم إنشاء نسخة احتياطية `.bak` من كل ملف تم تعديله:

| الملف الأصلي | النسخة الاحتياطية |
|-------------|------------------|
| `backend/services/grades.py` | `backend/services/grades.py.bak` |
| `backend/services/performance.py` | `backend/services/performance.py.bak` |
| `backend/database/database.py` | `backend/database/database.py.bak` |
| `config.py` | `config.py.bak` |
| `app.py` | `app.py.bak` |

---

## متطلبات إضافية

لتفعيل Connection Pooling في بيئة PostgreSQL، يجب تثبيت مكتبة `psycopg_pool`:

```bash
pip install psycopg_pool
```

> إذا لم تكن المكتبة مثبتة، سيعمل التطبيق بشكل طبيعي مع إنشاء اتصال جديد لكل طلب (السلوك القديم) مع تحذير في الـ log.

---

## التوافقية

جميع التعديلات تحافظ على:
- **التوافق مع SQLite:** لا تغيير في سلوك SQLite.
- **التوافق مع PostgreSQL:** السلوك القديم يعمل كـ fallback إذا لم تكن `psycopg_pool` مثبتة.
- **التوافق مع الكود الحالي:** لم يتم تغيير أي واجهة (API) موجودة. الدوال الجديدة إضافية فقط.
