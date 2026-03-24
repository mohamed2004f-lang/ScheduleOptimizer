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
- Database: SQLite (`backend/database/mechanical.db`)
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

_Last generated: 2026-03-24 03:47_

- `3cdd195` (2026-03-19): تحسين واجهة خطط التسجيل والتسجيلات الفعلية
- `3f614a6` (2026-03-18): تحديث تقارير الرسوب/غير المنجزة وتحسين صلاحيات النظام والواجهات
- `e3009e8` (2026-03-17): تحديثات نظام التسجيل والتقارير (طلبات الإضافة/الإسقاط، الاختياريات، التقارير الجديدة، وتحسين واجهات الأداء وكشف الدرجات)
- `f879829` (2026-03-15): تحديثات: تعارضات الجدول، الجدول النهائي، تعديل الدرجات واختيار المقرر، خطة التخرج للطالب، قواعد أكاديمية، تحسينات واجهات
- `fd0b3a9` (2026-03-13): تحديثات التقارير والإشراف وكشف الدرجات
- `c26ba08` (2025-12-18): Update login credentials and remove default hint for security
- `ef7e367` (2025-12-18): 🔒 Major security and architecture improvements
- `41e92c2` (2025-12-18): Initial commit

<!-- AUTO_LATEST_CHANGES_END -->
