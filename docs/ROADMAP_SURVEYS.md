# خارطة طريق منصة الاستبيانات (و-0 → و-5)

## و-0 — البنية الأساسية
- [x] جداول: `survey_templates`, `survey_questions`, `survey_responses`, `survey_answers`
- [x] `backend/core/survey_platform.py` — تعريف القوالب والبذر
- [x] `backend/services/multi_surveys.py` — خدمة الإرسال والتجميع
- [x] بذر عند تشغيل التطبيق + أول طلب

## و-1 — دور الموظف
- [x] دور `staff` في `auth` و`users`
- [x] استبيانات: `staff_workplace`, `staff_student_services`
- [x] مركز «الاستبيانات» `/academic_quality/surveys`

## و-2 — أستاذ → قيادة
- [x] `faculty_hod` — رئيس القسم (سري، حد أدنى 3)
- [x] `faculty_dean` — عميد / إدارة كلية

## و-3 — أستاذ → العملية التعليمية
- [x] `faculty_educational_process` — إقفال، امتحانات، PLO

## و-4 — توسيع الطالب
- [x] `student_services`, `student_facilities`
- [x] رابط من صفحة تقييم المقررات + مركز الاستبيانات
- [x] `student_course` يبقى عبر `/students/evaluations` (مسار قديم)

## و-5 — تجميع وتقارير
- [x] `/academic_quality/surveys/results` — نتائج مجمّعة (بعد الحد الأدنى)
- [x] `survey_metrics` في `compute_quality_metrics`
- [x] تصدير Excel: `/academic_quality/surveys/export.xlsx`
- [x] اختبارات: `tests/test_multi_surveys.py`

## بنود الاستبيان (10 لكل قالب)
- [x] صياغة أكاديمية مستوحاة من SERU/IDEA/NASPA ومعايير ضمان الجودة
- [x] ترقية تلقائية للقواعد القديمة (إضافة البنود الناقصة دون حذف المخصّص)

## إدارة البنود (موحّدة)
- [x] `/academic_quality/survey_admin` — قائمة منسدلة بكل القوالب (`?template=`)
- [x] APIs مع `template_code`: إضافة / تعديل / ترتيب / حذف
- [x] `student_course` → جدول `evaluation_survey_questions` (تقييم المقرر)
- [x] باقي القوالب → `survey_questions`

## القادم (اختياري)
- ربط تلقائي أعمق بمؤشرات الاعتماد SS-02 / FF
- استبيان خريج / شريك مجتمعي

## مرجع
`backend/core/survey_platform.py`, `backend/services/multi_surveys.py`, `backend/services/survey_platform_routes.py`, `frontend/templates/survey_*.html`
