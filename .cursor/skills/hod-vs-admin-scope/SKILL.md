---
name: hod-vs-admin-scope
description: >-
  Department scope for head_of_department versus college admin roles. Use when
  رئيس القسم sees fewer rows than admin, resolve_effective_department_scope_id,
  head_home_department_id, or department_id filters on reports/surveys/schedule.
---

# HOD vs admin scope

## Roles

| Role | Typical scope |
|------|----------------|
| `admin` / `admin_main` / `system_admin` | College-wide (`department_id=None`) unless session scope set |
| `college_dean` / `academic_vice_dean` | Often college-wide or optional dept picker |
| `head_of_department` | Home department only |

## Resolution helpers

- `resolve_effective_department_scope_id(conn, username)` — active scope
- `head_home_department_id(conn, username)` — HOD home dept
- `get_admin_department_scope_id()` — session-selected admin scope

Survey results: `_user_department_id` in `survey_platform_routes.py` feeds analytics
`department_id`. Fix missing HOD rows in the **filter logic**, not by removing scope.

## Rules

1. Never “fix” HOD emptiness by dropping department filters for that role.
2. Prefer expanding membership rules (schedule **or** teaching group **or** instructor) so legitimate dept rows appear.
3. Admin screens may offer `department_id` query param; HOD must ignore foreign dept ids.
4. When comparing admin vs HOD screenshots, check both the SQL/scope filter and whether
   `department_name` display comes from schedule vs teaching group.

## Related

- Survey by-section: skill `survey-results-scope`
- Schedule/GENERAL overlay: skill `teaching-groups-ab`
