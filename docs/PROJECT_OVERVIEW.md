# ScheduleOptimizer - Project Overview

## Purpose

ScheduleOptimizer is an academic operations platform for managing student data, registrations, enrollment plans, transcripts, academic status, and decision-support reports in one workflow.

---

## Core Workflow

1. Student prepares an enrollment plan (draft/submit).
2. Supervisor / Head of Department / Admin reviews pending plans.
3. Approved plans are moved to actual registrations.
4. Registrations are migrated to transcript/grades per term.
5. System computes GPA, completed units, academic status, and uncompleted courses.
6. Reports support planning decisions (open courses, workload, faculty allocation).

---

## Main Modules

- Student Management (CRUD, import/export)
- Courses & Prerequisites
- Actual Registrations (add/drop/save with immediate refresh)
- Enrollment Plans (Draft, Pending, Approved, Rejected)
- Transcript & Grade Management
- Performance & Academic Status
- Student Affairs Reports:
  - Add/Drop report
  - Electives report
  - Comprehensive uncompleted courses report
  - Uncompleted courses per student
- API layer (`/api/v1/students`)

---

## Security & Access Control

- Authentication via Flask-Login
- CSRF protection for web UI
- Role-based permissions:
  - `admin_main`
  - `head_of_department`
  - `instructor`
  - `student`
- Additional capability flags (e.g., supervisor)

---

## Technology Stack

- Backend: Flask (Blueprint-based architecture)
- Database: PostgreSQL (`DATABASE_URL` in `.env`)
- Frontend: HTML + Bootstrap + JS (fetch APIs)
- Reports: Excel/PDF export

---

## Current Focus Areas

- Faster academic review decisions through in-context student summary
- Better visibility of uncompleted courses and risk indicators
- UI reliability (reduce redirect-related fetch issues)
- Cleaner operations runbook and deployment workflow

<!-- AUTO_LATEST_CHANGES_START -->
## Latest Changes (Auto)

_Last generated: 2026-07-17 23:00_

- `e9106e6` (2026-07-17): نسخة يومية تلقائية 2026-07-17
- `5b142ad` (2026-07-15): إصلاح إنشاء جداول نشر الدرجات على PostgreSQL عند اعتماد رئيس القسم.
- `490944b` (2026-07-15): إضافة رفع يومي آمن إلى GitHub عبر سكربت ومهمة مجدولة الساعة 23:00.
- `7297962` (2026-07-15): إضافة تقارير جودة المقررات (معاينة/PDF) مع توصيات آلية، وتوسيع الجودة والاعتماد والمساعد والتصديرات.
- `c9e6917` (2026-07-09): إصلاح إرسال استبيان الخريج: تجاوز CSRF لمسار الدعوة العامة وإرسال الرمز من الصفحة.
- `c12a765` (2026-07-03): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `218ffb6` (2026-07-03): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `b71e2ec` (2026-07-02): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `5baed0c` (2026-07-02): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `e7d1245` (2026-07-02): توحيد نطاق القسم عبر الخدمات وإصلاح ثبات بنود الاستبيانات بعد التعديل اليدوي.

<!-- AUTO_LATEST_CHANGES_END -->
