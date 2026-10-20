---
name: scheduleoptimizer-ui-rtl
description: >-
  Designs and edits ScheduleOptimizer web UI (Jinja + Bootstrap RTL admin
  pages). Use when changing frontend/templates, CSS under frontend/static/css,
  page layout, Arabic RTL forms, dashboards, or user-facing HTML pages in this
  repo.
---

# ScheduleOptimizer UI (RTL)

## Stack

- Templates: `frontend/templates/*.html` (Jinja2), base `base_nav.html`
- CSS: `frontend/static/css/` especially `ui-consistency.css`, `theme-mechanical-engineering.css`
- JS: Bootstrap bundle + page scripts; prefer existing patterns over new frameworks
- Direction: Arabic **RTL** (`dir="rtl"`). Keep LTR islands (`dir="ltr"`) for times, codes, IDs, dates, percents.

## Product UI rules (admin app — not a marketing landing)

1. Preserve existing Bootstrap structure (`page-title`, `page-subtitle`, `card shadow-sm`, `table-sm`, `btn-sm`).
2. One job per section: clear heading + short helper text; avoid dashboard clutter on simple forms.
3. Prefer tables/lists for data; cards only when they wrap a real interaction.
4. Do not introduce Inter/Roboto purple gradients, glow pills, or decorative hero marketing layouts into staff pages.
5. Mobile: forms and tables must remain usable; use `table-responsive`, stacked `row g-2` where already used.
6. After template/CSS changes that must show live → follow `scheduleoptimizer-deploy`.

## Arabic / bidi

- Labels Arabic; technical IDs and file names stay English in code.
- Numbers and `HH:MM-HH:MM` slots: `dir="ltr"` on the value.
- Print forms: see skill `arabic-rtl-forms-print`.

## Do not

- Add React/Vue for a one-off page (system is server-rendered).
- Rewrite global nav/theme unless asked.
- Break CSP/`nonce` script patterns in templates.
