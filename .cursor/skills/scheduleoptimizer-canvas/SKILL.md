---
name: scheduleoptimizer-canvas
description: >-
  When to use a Cursor Canvas for ScheduleOptimizer analytical deliverables.
  Use when presenting survey aggregates, enrollment/scope comparisons,
  architecture reviews, term-window audits, or any large structured table the
  user should reopen beside chat — not for routine code fixes.
---

# ScheduleOptimizer + Cursor Canvas

## Built-in skill (required for implementation)

Before creating or editing any `.canvas.tsx` file, **read** the Cursor built-in skill:

`C:\Users\BARCODE\.cursor\skills-cursor\canvas\SKILL.md`

(and SDK types under that folder’s `sdk/` when props are unclear).

## When to use a canvas in this project

Use a canvas when the **deliverable is analysis the user will revisit**, e.g.:

- Survey results breakdown (HOD vs admin scope, enrolled vs responses)
- Term-window / registration-guard audits across operations
- Teaching-group vs schedule department mismatches
- Architecture or security review summaries with categorized findings
- Large comparison tables (semesters, departments, response rates)

## When NOT to use a canvas

- Fixing a bug, editing Jinja/Bootstrap pages, or deploying Docker
- Short factual answers («أين الملف؟»)
- Changing `registration_form_print` / Word templates (use HTML/DOCX, not canvas)
- Work whose home is an existing app page (`/academic_quality/surveys/results`)

## File location

Write canvases only to:

`C:\Users\BARCODE\.cursor\projects\c-Users-BARCODE-ScheduleOptimizer\canvases\<name>.canvas.tsx`

- One file per canvas; import only from `cursor/canvas`
- Embed data inline (no `fetch`)
- Link the absolute path in the chat reply when mentioning the canvas

## Design (canvas SDK)

Flat, minimal: no gradients, emojis, or box-shadows. Label charts with title, axes, units, source. Omit empty sections instead of “No data” placeholders.
