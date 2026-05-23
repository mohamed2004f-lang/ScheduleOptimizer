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

_Last generated: 2026-05-24 00:48_

- `099787c` (2026-05-23): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `a2cc901` (2026-05-22): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `149db1f` (2026-05-22): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `7e3e49b` (2026-05-22): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `247d45d` (2026-05-19): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `635d9a2` (2026-05-18): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `a195b2a` (2026-05-15): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `3a6ee8b` (2026-05-04): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `83347e9` (2026-05-03): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `9bf39dd` (2026-05-03): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1

<!-- AUTO_LATEST_CHANGES_END -->
