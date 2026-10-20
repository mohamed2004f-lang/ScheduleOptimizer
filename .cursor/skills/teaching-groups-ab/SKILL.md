---
name: teaching-groups-ab
description: >-
  Teaching groups A/B, GENERAL overlay, and registration–schedule linking. Use
  when مجموعات التدريس, A/B, اتجاه عام overlay, attach_schedule_slot, or
  specialty departments vs GENERAL courses.
---

# Teaching groups A/B

## Key files

- `backend/services/teaching_groups.py` — groups, roster, attach to schedule
- `backend/services/schedule_general_overlay.py` — GENERAL courses on specialty views
- `frontend/templates/teaching_groups_setup.html`, `schedule_form.html`, `registrations_form.html`

## Concepts

- **Teaching group**: logical section (often A/B) with `department_id`, `group_code`, `instructor_id`.
- **GENERAL**: college-wide courses; specialty HOD must not freely add them as specialty-owned schedule rows (block + messaging).
- **Overlay**: show GENERAL offerings to specialty students/depts without rewriting ownership.
- Prefer **per-student** A/B assignment over mass department binding when product rules require it.

## Pitfalls

- `schedule.department_id` may be NULL or GENERAL while the teaching group is specialty — do not assume they match.
- Edit flows need explicit group picker / `allow_reassign` when TG should remain editable.
- Enrollment counts for surveys/analytics should follow `teaching_group_id` when present.

## Safe change pattern

1. Identify whether the course is GENERAL or specialty-owned.
2. Check `teaching_groups` for the term before inventing new schedule-only sections.
3. Update overlay + attach helpers together; add a focused test under `tests/`.
