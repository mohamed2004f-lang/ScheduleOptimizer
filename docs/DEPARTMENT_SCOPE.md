# نطاق القسم — استيراد وتصدير

## المبدأ

عند تفعيل نطاق قسم (رئيس قسم، أو مسؤول/عميد/موظف بقسم محدد في الجلسة):

1. **التصدير** يستخدم نفس فلترة **القائمة** على الشاشة.
2. **الاستيراد** يربط السجلات الجديدة بقسم المنفّذ ويرفض الصفوف خارج النطاق.
3. **لا** يُسمح بتصدير/استيراد بيانات قسم آخر «بالخطأ».
4. **مقررات الاتجاه العام** (`college_general` / قسم `GENERAL`) تظهر لجميع الأقسام ولا تُربط بقسم تخصص عند الاستيراد.
5. **المقررات المشتركة** (سجل `college_shared_catalog`) — موحّدة GS أو برموز مختلفة أو subset؛ إدارة من `/college_shared_catalog_page`.
6. **استيراد Excel:** إن وُجد نفس `course_code` لمقرر باسم آخر (مثل `GS 201`) يُتجاهل الصف ويُعاد في `ignored` دون إيقاف بقية الاستيراد.
7. **توجيه التقارير والاستبيانات** — `resolve_course_responsible_department_id`: قسم **عرض المقرر** (جدول/مجموعة تدريس) وليس قسم منزل الأستاذ.

## الدوال المركزية

في `backend/core/department_scope_policy.py`:

| الدالة | الاستخدام |
|--------|-----------|
| `resolve_effective_department_scope_id` | معرّف القسم الفعّال |
| `resolve_college_general_department_id` | قسم GENERAL |
| `resolve_course_responsible_department_id` | **قسم مختص للإشعارات/التقارير/الاستبيانات** |
| `course_is_college_general` | هل المقرر اتجاه عام؟ |
| `course_is_college_shared_catalog` | هل المقرر في السجل المشترك؟ |
| `courses_department_scope_filter` | فلترة قائمة/تصدير (قسمي + GENERAL + NULL) |
| `resolve_import_owning_department_id` | ملكية الاستيراد |
| `courses_export_sql_and_params` | تصدير المقررات |
| `course_in_actor_scope` / `assert_course_in_actor_scope` | تحقق مقرر |
| `student_in_actor_scope` / `assert_student_in_actor_scope` | تحقق طالب |
| `resolve_import_department_binding` | ربط تلقائي بعد استيراد Excel |
| `resolve_registration_course_scope_sql` | تقارير التسجيل |
| `backfill_courses_owning_department_from_schedule` | ترحيل `owning_department_id` |
| `invalidate_department_scope_list_caches` | إبطال كاش القوائم |

## مسارات مغطاة

- `/courses/export/*` — مقررات القسم
- `/courses/import/excel` — ربط `owning_department_id`
- `/students/export/*` — طلاب مسموحون للدور
- `/students/import/excel` — ربط قسم/برنامج
- `/students/import_registrations` — تحقق طالب + مقرر
- `/grades/import/semester` — تحقق طلاب ومقررات
- `/schedule/import/excel` — مقررات القسم + `department_id`
- `/schedule/export/*` — صفوف الجدول للقسم
- `/students/course_registration_counts/*` — طلاب + مقررات القسم

## ترحيل البيانات القديمة

```bash
# الإنتاج (Docker) — يجب التشغيل داخل الحاوية لأن قاعدة البيانات الفعلية هناك:
docker compose exec web python scripts/migrate_college_general_courses.py --dry-run
docker compose exec web python scripts/migrate_college_general_courses.py

# تطوير محلي فقط (إذا كان DATABASE_URL يشير لنفس القاعدة):
python scripts/migrate_college_general_courses.py --dry-run
python scripts/backfill_courses_department.py --dry-run
python scripts/backfill_courses_department.py
python scripts/backfill_courses_department.py --department-id 3
```

## سجل المقررات المشتركة

```bash
# تعبئة أولية (داخل Docker):
docker compose exec web python scripts/seed_college_shared_catalog.py

# واجهة الإدارة:
/college_shared_catalog_page
```

أنواع `share_type`: `unified` | `multi_code` | `subset`

## الاختبارات

```bash
pytest tests/test_courses_import_excel.py tests/test_department_scope_import_export.py tests/test_college_shared_catalog.py -q
```
