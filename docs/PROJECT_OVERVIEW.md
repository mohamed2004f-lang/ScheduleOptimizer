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

_Last generated: 2026-04-15 21:40_

- `2d88cc7` (2026-04-15): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `c96a622` (2026-04-13): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `84f5b29` (2026-04-13): y
- `4fda95c` (2026-04-12): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `073fa9d` (2026-04-11): y
- `7276dc7` (2026-04-11): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `3362fe7` (2026-04-11): y
- `136bb8e` (2026-04-10): Y
- `958b8aa` (2026-04-10): & c:/Users/BARCODE/ScheduleOptimizer/.venv/Scripts/Activate.ps1
- `dc921fb` (2026-04-03): y

<!-- AUTO_LATEST_CHANGES_END -->
