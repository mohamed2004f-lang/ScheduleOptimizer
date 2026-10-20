---
name: survey-results-scope
description: >-
  Course-eval survey results scoping for HOD vs admin and enrolled-count
  resolution. Use when نتائج الاستبيانات, تقييم المقرر حسب الشعبة, مسجّلون
  (تقدير), historical_orphan, or head_of_department sees fewer sections than
  admin.
---

# Survey results scope

## Key files

- `backend/services/survey_analytics.py` — filters, enrollment, section summaries
- `backend/services/survey_platform_routes.py` — passes `department_id` for HOD
- `frontend/templates/survey_results.html` — by-section table

## Department filter (`_course_eval_dept_filter`)

An evaluation belongs to a department if **any** of:

1. `schedule.department_id` via `e.section_id`
2. `teaching_groups.department_id` via `e.teaching_group_id`
3. `instructors.department_id` via `e.instructor_id`

Do not filter HOD results on schedule department alone.

Admin / college scope: `department_id=None` → no dept filter (all sections).

## Enrolled counts

Order for past terms (`is_course_eval_historical_term`):

1. `term_registration_archives` with **flexible semester aliases**
2. `grades` with same aliases
3. Live `registrations` / teaching-group counts
4. Else `historical_orphan` (min `*3`) — scores may show with enrolled `0`

Aliases: `ربيع 25-26` ↔ `ربيع 2025/2026` via `_semester_label_aliases` / `parse_semester_label`.

Columns:
- `enrolled_count` — section/group estimate
- `course_registration_count` — course total

## When fixing bugs

Reuse `_course_eval_dept_filter`; do not paste duplicate `EXISTS (schedule…)` blocks.
Prefer archive-first for closed/past semesters before blaming the 50% rule.
