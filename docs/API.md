# مرجع API — ScheduleOptimizer

واجهة JSON للمسارات الأكثر استخداماً. معظم المسارات تتطلب تسجيل دخول وملف تعريف ارتباط (session cookie).

## المصادقة

| Method | Path | الوصف |
|--------|------|--------|
| POST | `/auth/login` | تسجيل الدخول `{ username, password, remember? }` |
| GET | `/auth/check` | حالة الجلسة الحالية |

## بوابة الإدخال (index)

| Method | Path | الوصف |
|--------|------|--------|
| POST | `/index/parse-excel` | رفع Excel وتحويله إلى JSON |
| GET | `/index/template/<kind>` | قالب Excel (`students`, `schedule`, `registrations`) |
| POST | `/submit-data` | حفظ دفعة `{ students, schedule, registrations }` |
| POST | `/run-optimize` | تشغيل المحسّن `{ max_alternatives_per_section?, move_cost?, add_room_conflict?, add_instructor_conflict? }` |

استجابة `/run-optimize` الناجحة (متزامن):

```json
{
  "status": "ok",
  "schedule_rows": 12,
  "proposed_moves_count": 3,
  "conflict_count": 2,
  "optimizer": "cp_sat"
}
```

`optimizer`: `cp_sat` (OR-Tools) أو `rule_based_slots` (احتياط).

### تحسين غير متزامن (جداول كبيرة أو `"async": true`)

```json
POST /run-optimize
{ "async": true, "max_alternatives_per_section": 3 }
→ 202 { "status": "accepted", "job_id": "...", "poll_url": "/schedule/optimize_job/..." }
GET /schedule/optimize_job/<job_id>
→ { "status": "completed", "result": { ... } }
```

مع `CELERY_BROKER_URL` يُستخدم Celery+Redis؛ وإلا خيط محلي.

## الجدول والتحسين

| Method | Path | الوصف |
|--------|------|--------|
| GET | `/schedule/rows` | صفوف الجدول |
| POST | `/schedule/run_optimize` | نفس `/run-optimize` |
| GET | `/schedule/proposed_moves` | قائمة اقتراحات النقل |
| POST | `/schedule/proposed_move/<section_id>` | تطبيق اقتراح `{ move_id? }` |
| POST | `/proposed_move/<section_id>` | توافقية — نفس التطبيق |

## النتائج

| Method | Path | الوصف |
|--------|------|--------|
| GET | `/results_data` | `{ conflict_report, proposed_moves, optimized_schedule }` |
| POST | `/students/recompute_conflicts` | إعادة حساب تعارضات الطلبة |

## رموز الأخطاء الشائعة

| HTTP | code | المعنى |
|------|------|--------|
| 400 | VALIDATION_ERROR | مدخلات غير صالحة |
| 401 | UNAUTHORIZED | غير مسجّل |
| 403 | FORBIDDEN | صلاحية غير كافية |

## CSRF

لطلبات POST من المتصفح أرسل رأس `X-CSRFToken` من `<meta name="csrf-token">` أو اعتمد على `common.js` الذي يحقن الرمز تلقائياً.

## التخزين المؤقت

قوائم `/students/list`, `/courses/list`, `/schedule/rows` تُخزَّن مؤقتاً (افتراضي 60ث). متغيرات البيئة:

- `CACHE_TIMEOUT` — مدة الثواني
- `CACHE_REDIS_URL` — Redis اختياري
- `CACHE_TYPE` — `SimpleCache` افتراضياً

## اختبارات E2E

```bash
pip install -r requirements-dev.txt
playwright install chromium
# شغّل الخادم ثم:
set E2E_BASE_URL=http://127.0.0.1:5000
pytest tests/e2e -m e2e
```
