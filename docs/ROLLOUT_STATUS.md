# حالة تنفيذ مجموعات التدريس — 2026-03-11

## المرحلة 0 — تجهيز

| البند | الحالة | ملاحظة |
|--------|--------|--------|
| نسخة PostgreSQL (`pg_dump`) | ⚠️ | `pg_dump` غير موجود في PATH — أضفه أو انسخ من لوحة الإدارة |
| تدقيق baseline | ✅ | `python scripts/_audit_program_course_sections.py` |

## المرحلة 1 — ترحيل التشغيل (ربيع 25-26)

| البند | قبل | بعد |
|--------|-----|-----|
| `registrations.teaching_group_id` | 0 / 131 | **131 / 131** |
| `course_evaluations` backfill | — | **65** مرتبطة |
| تسجيلات بلا مجموعة | 131 | **0** |
| مجموعات بلا تقييم | — | **3** (مقررات بلا أي تقييم بعد) |

أمر الترحيل:
```bash
python scripts/backfill_teaching_groups.py
```

## المرحلة 2 — إلغاء `program_course_sections`

| البند | الحالة |
|--------|--------|
| بطاقة الكتalog | ✅ محذوفة |
| API `/sections`, `/section/save`, `/section/delete` | ✅ محذوفة |
| `check_general_sections_capacity` | ✅ no-op (السعة عبر `teaching_groups` لاحقاً) |

## المرحلة 3 — حذف الجدول

| البند | الحالة |
|--------|--------|
| `DROP TABLE program_course_sections` | ✅ عند `ensure_tables()` / إعادة تشغيل التطبيق |
| إزالة من `TABLES_SCHEMA` + `conftest` | ✅ |

## المرحلة 4 — السياسات

| البند | القيمة |
|--------|--------|
| `REG_PROGRAM_COURSE_MODE` | `warn` (في `.env.example`) |
| Runbook | `docs/TEACHING_GROUPS.md` |

## المرحلة 5 — اختياري (بعد المراقبة)

| # | البند | الحالة |
|---|--------|--------|
| 5.1 | واجهة الدرجات + `teaching_group_id` | ✅ |
| 5.5 | مصطلح «مجموعة تدريس» في الدرجات/مقرراتي | ✅ |
| 5.6 | نسخ PostgreSQL (`pg_dump`) | ✅ — انظر `docs/PG_BACKUP.md` |
| 5.2 | سعة `capacity_max` | ⏸️ عند الحاجة |
| 5.3 | ربط `program_course_id` (5/131) | ⏸️ عند الحاجة |
| 5.4 | split A/B | ⏸️ لا مجموعات split حالياً |

## تحقق سريع

```bash
python scripts/_audit_program_course_sections.py
python -m pytest tests/test_teaching_groups_phases_3_6.py tests/test_teaching_groups_registrations.py -q
```
