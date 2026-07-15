# ScheduleOptimizer — خارطة طريق الاعتماد المؤسسي

مرجع منفصل عن [مسار MECH](ROADMAP_ACADEMIC_PATHWAY.md).

## الهدف

نظام «معيار → مؤشر → تقييم → دليل» متوافق مع معايير المركز الوطني، مدمج مع ضمان الجودة الحالي دون استبداله.

## منفّذ

### هـ-1 — هيكل الكتالوج وخريطة الامتثال
- [x] جداول: `accreditation_standards`, `accreditation_indicators`, `accreditation_assessments`
- [x] Seed افتراضي: **15 معياراً / 15 مؤشراً** عبر 7 محاور (`backend/core/accreditation_catalog.py`)
- [x] صفحة `/academic_quality/accreditation/map` — خريطة امتثال + تقييم يدوي لكل مؤشر
- [x] API: `compliance_map`, `ensure_catalog`, `assessment/save`

## منفّذ (تتابع)

### هـ-2 — مؤشرات آلية
- [x] `backend/services/accreditation_metrics.py` — 9 مؤشرات آلية/مختلطة
- [x] `POST /academic_quality/api/accreditation/compute_auto` + معاينة `compute_auto/preview`
- [x] زر «احسب من النظام» في خريطة الامتثال
- [x] مرجع [المركز الوطني — التعليم الجامعي](https://qaa.ly/%d8%a7%d9%84%d8%aa%d8%b9%d9%84%d9%8a%d9%85-%d8%a7%d9%84%d8%ac%d8%a7%d9%85%d8%b9%d9%8a/)
- [x] توثيق أدوار التنسيق (منسق جودة / مجتمع / بحث — تشغيلياً عبر رئيس القسم)

### هـ-3 — أدلة ومرفقات
- [x] جدول `accreditation_evidence` + مجلد `backend/uploads/accreditation_evidence`
- [x] `backend/services/accreditation_evidence.py` — رفع ملف / رابط / حذف منطقي
- [x] قائمة تحقق مستندات المركز (`backend/core/accreditation_evidence_catalog.py`)
- [x] APIs: `evidence/list`, `upload`, `link`, `file/<id>`, `DELETE`, `evidence/checklist`
- [x] واجهة: قائمة تحقق + عمود «أدلة» لكل مؤشر + modal إدارة (`accreditation_compliance_map.html`)
- [x] `evidence_count` في `build_compliance_map`
- [x] اختبارات: `tests/test_accreditation_evidence.py`

### هـ-4 — إدخالات يدوية موسّعة
- [x] جدول `accreditation_manual_inputs` — مرافق، مالية، حوكمة، مجتمع/بحث
- [x] جدول `accreditation_improvement_plans` — خطط تحسين مرتبطة بمؤشر (اختياري)
- [x] `backend/services/accreditation_manual.py` + APIs حفظ/قائمة
- [x] واجهة في خريطة الامتثال (نماذج + جدول خطط + modal)

### هـ-5 — تقارير الاعتماد
- [x] `backend/core/accreditation_workbook.py` — أوراق Excel + HTML لـ PDF
- [x] `GET .../export/xlsx` و `GET .../export/pdf` (دفتر اعتماد كامل)
- [x] `backend/services/accreditation_catalog_import.py` — استيراد Excel
- [x] `GET .../import_catalog/template` + `POST .../import_catalog` (admin)
- [x] `resolve_catalog_version` — أحدث إصدار نشط بعد الاستيراد
- [x] اختبارات: `test_accreditation_manual.py`, `test_accreditation_workbook.py`

### تحسينات واجهة خريطة الامتثال
- [x] تبويبات: امتثال | أدلة | خطط | إدخال يدوي | إدارة
- [x] فلتر محور + حالة + بحث نصي (عميل)
- [x] AJAX: حفظ يدوي/خطة/تقييم/احسب آلياً بدون إعادة تحميل كاملة
- [x] ربط الإدخال اليدوي → مؤشرات (`sync_manual_inputs_to_indicators`: FF-01-1, FF-02-1, CR-01-1, CR-02-1, GV-01-1)
- [x] قائمة إصدارات الكتالوج + `GET .../catalog_versions` + `catalog_version` في خريطة الامتثال والتصدير
- [x] `frontend/static/js/accreditation_compliance_map.js` — منطق الواجهة خارج القالب
- [x] اختبارات: `tests/test_accreditation_ux.py`, `test_manual_sync_updates_indicators`

## القادم

- [x] تشغيل يومي على **مؤسسي + برامجي (QAA)** فقط — الكتالوج الداخلي `2026.1` أرشيف (الخيار ب)
- [x] نطاق برامجي عبر `programs` مع مواءمة حالية **برنامج = قسم** (جاهز لمسارات لاحقاً)
- [x] أرشيف القسم (محاضر/قرارات/صادر/وارد/ملاحظات) + دليل أرشفة + اقتراح ربط يدوي QAA + مساعد اقتراح/صياغة
- _(اختياري لاحق)_ أدوار منسقي الجودة كصلاحيات؛ توسيع فهرسة المساعد

## محاور التشغيل

| النطاق | الكتالوج | وحدة التقييم |
|--------|----------|----------------|
| مؤسسي | `QAA-2023.4-INST` | الكلية |
| برامجي | `QAA-2023.4-PROG-UG` | برنامج (`programs.id`) — اليوم أساس القسم |

## مرجع تقني

`backend/core/accreditation_catalog.py`, `backend/core/accreditation_workbook.py`, `backend/core/accreditation_evidence_catalog.py`, `backend/services/accreditation_metrics.py`, `backend/services/accreditation_evidence.py`, `backend/services/accreditation_manual.py`, `backend/services/accreditation_catalog_import.py`, `backend/services/institutional_accreditation.py`, `frontend/templates/accreditation_compliance_map.html`, `frontend/static/js/accreditation_compliance_map.js`
