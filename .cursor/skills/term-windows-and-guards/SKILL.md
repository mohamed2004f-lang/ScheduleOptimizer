---
name: term-windows-and-guards
description: >-
  Explains academic calendar term windows and write guards for registrations
  add/drop. Use when saving registrations fails with نافذة مغلقة, editing
  التقويم الأكاديمي, OP_REGISTRATION_WRITE, add_courses, drop_courses, or
  term_windows sync.
---

# Term windows and write guards

## Key files

- `backend/services/term_engine.py` — `WINDOW_CATALOG`, `OPERATION_WINDOWS`, `assert_term_operation`
- `backend/services/students.py` — `_registration_write_blocked` → `OP_REGISTRATION_WRITE`
- `backend/services/academic_calendar.py` — calendar titles / item numbers

## Operations

| Operation | Windows (any open allows) |
|-----------|---------------------------|
| `OP_REGISTRATION_WRITE` | renewal, new, **add_courses**, **drop_courses** |
| `OP_ADD_COURSE` | add_courses, renewal, new |
| `OP_DROP_COURSE` | drop_courses, renewal, new |
| `OP_ENROLLMENT_PLAN_*` | renewal, new only |

Admin save of actual registrations uses `OP_REGISTRATION_WRITE`, not renewal alone.

## Window open rules

`window_open_on(starts, ends, today)`:
- Deadline-only (`starts` null, `ends` set) is open while `today <= ends`.
- If no scheduled dated windows exist for the operation keys → allow (unset does not block).

## Calendar vs guard

UI dates live in academic calendar rows; guards read `term_windows`.
Saving the calendar must sync windows (`sync_windows_from_calendar_items` / `on_calendar_saved`).
Changing only the calendar display without sync will not reopen a closed guard.

## Debug checklist

1. Confirm current ops semester label / `term_key`.
2. Inspect `term_windows` for `registration_renewal`, `registration_new`, `add_courses`, `drop_courses`.
3. Check stage lock (`assert_term_writable`) and `term_master.status == closed`.
4. Error text «التسجيلات» = `OP_REGISTRATION_WRITE`; «إضافة مقرر» = `OP_ADD_COURSE`.
