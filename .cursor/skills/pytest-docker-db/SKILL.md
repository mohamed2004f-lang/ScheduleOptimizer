---
name: pytest-docker-db
description: >-
  Running ScheduleOptimizer pytest against shared Postgres fixtures. Use when
  writing or debugging tests, auth_client, db_conn, or when tests touch live
  schedule/registrations/survey tables.
---

# Pytest and Docker DB

## Reality

Local pytest often uses the configured Postgres (`ACTIVE DATABASE: …`) via
`tests/conftest.py` fixtures — not an isolated throwaway SQLite file.

## Fixtures

- `db_conn` — shared connection; commit carefully; prefer unique names (`uuid` suffix).
- `auth_client` — logged-in admin (`admin-test`); session-scoped login.
- Role-specific: `student_auth_client`, `instructor_auth_client`.

## Practices

1. Namespace test data (`course`, `semester`, `student_id`) so parallel/repeat runs do not collide.
2. Prefer unit-testing helpers (`assert_term_operation`, `_fetch_course_eval_section_groups`) over full HTTP when enough.
3. Monkeypatch session/scope helpers when testing HOD/admin filters.
4. Clean up or use unique keys; do not delete unrelated production-looking rows by broad `DELETE`.

## Commands

```powershell
python -m pytest tests/test_foo.py::test_name -q --tb=short
```

After green tests that change runtime behavior, deploy with the `scheduleoptimizer-deploy` skill.
