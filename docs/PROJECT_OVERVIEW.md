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

_Last generated: 2026-09-24 23:00_

- `a1eb06d` (2026-09-22): نسخة يومية تلقائية 2026-09-22
- `91f35b6` (2026-09-20): نسخة يومية تلقائية 2026-09-20
- `24e017b` (2026-09-15): نسخة يومية تلقائية 2026-09-15
- `6494790` (2026-09-13): نسخة يومية تلقائية 2026-09-13
- `b875ace` (2026-09-11): نسخة يومية تلقائية 2026-09-11
- `b1c418f` (2026-09-09): نسخة يومية تلقائية 2026-09-09
- `b1588e0` (2026-09-08): نسخة يومية تلقائية 2026-09-08
- `b629bb8` (2026-09-07): نسخة يومية تلقائية 2026-09-07
- `632f4c8` (2026-08-22): نسخة يومية تلقائية 2026-08-22
- `1435eae` (2026-08-20): نسخة يومية تلقائية 2026-08-20

<!-- AUTO_LATEST_CHANGES_END -->
