# ScheduleOptimizer — خارطة طريق المسار الأكاديمي

## السياق (MECH)
- طلاب حاليون: داخل القسم بعد الاتجاه العام (`dept_admitted`).
- **155** وحدة تخرج **شاملة 36** اتجاه عام. **150/155** في سجل الطالب فقط.
- شعبة = برنامج (`MECH`, `MECH-PWR`, …). مقررات الشعبة في برنامج الشعبة.

## منفّذ
- [x] المرحلة أ + توسعة الشعب والكتالوج
- [x] **ب-1** `pathway_stage` في قائمة الطلاب
- [x] **ب-2** جسر PLO من مقرر الخطة
- [x] **ب-3** تأكيدات العمليات الجماعية
- [x] **ب-4** سجل تغييرات الجلسة (كتالوج)
- [x] **ج** حاسبة منجز/متبقي (155 شاملة 36): `pathway_progress.py`، API، واجهة طلاب + معاينة كتالوج
- [x] **د** شبكة مستويات + متطلبات سابقة، Excel (خطة/مسار/جماعي)، دفعات PROG_U1 (`college_pathway_cohort_from_join_year`)

## القادم

## مرجع
`backend/core/academic_pathway.py`, `pathway_plan_grid.py`, `pathway_export.py`, `pathway_progress.py`, `program_tracks.py`, `college_catalog.html`, `students_form.html`, `ilo_catalog.html`
