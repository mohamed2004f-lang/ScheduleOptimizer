# ScheduleOptimizer — خارطة طريق المسار الأكاديمي

## السياق (أقسام الكلية)
- **هدف تخرج القسم** (مصدر الحقيقة): `DEPT_GRADUATION_TARGETS` + لائحة `dept_graduation_min_units`
  — MECH **155**، CIVIL **161**، ELEC/RENEW **160** (شاملة 36 اتجاه عام).
- **نظام الوحدات التراثي 150/155**: حقل `students.graduation_plan` لطلاب **الميكانيكا** القدامى فقط (انتقالي).
  لا يُعرض كـ«خطة تخرج» لأقسام أخرى في شاشة الطلبة.
- شعبة = برنامج (`MECH`, `MECH-PWR`, …). مقررات الشعبة في برنامج الشعبة.
- API واجهة: `GET /students/graduation_plan/options` — هدف القسم + خيارات تراثية إن لزم.

## منفّذ
- [x] المرحلة أ + توسعة الشعب والكتالوج
- [x] **ب-1** `pathway_stage` في قائمة الطلاب
- [x] **ب-2** جسر PLO من مقرر الخطة
- [x] **ب-3** تأكيدات العمليات الجماعية
- [x] **ب-4** سجل تغييرات الجلسة (كتالوج)
- [x] **ج** حاسبة منجز/متبقي (155 شاملة 36): `pathway_progress.py`، API، واجهة طلاب + معاينة كتالوج
- [x] **د** شبكة مستويات + متطلبات سابقة، Excel (خطة/مسار/جماعي)، دفعات PROG_U1 (`college_pathway_cohort_from_join_year`)
- [x] **هـ** خطط التخرج حسب القسم: فصل 150/155 عن هدف القسم، مزامنة `PROG_MAJOR.min_total_units`، سياسات `DEPT`

## القادم

## مرجع
`backend/core/graduation_targets.py`, `backend/core/academic_pathway.py`, `pathway_plan_grid.py`, `pathway_export.py`, `pathway_progress.py`, `program_tracks.py`, `college_catalog.html`, `students_form.html`, `ilo_catalog.html`
