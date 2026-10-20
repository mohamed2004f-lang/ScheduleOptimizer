---
name: arabic-rtl-forms-print
description: >-
  Arabic RTL registration form print (HTML and Word). Use when استمارة تسجيل,
  registration_form_print, docxtpl, تاريخ التوقيعات, bidi, or Word/PDF print
  of student registration forms.
---

# Arabic RTL forms print

## Key files

- `frontend/templates/registration_form_print.html`
- `frontend/templates/registration_form_template.docx`
- `backend/services/enrollment.py` — `_build_registration_form_context`, `_fix_registration_docx_bidi`
- `scripts/build_registration_template.py` — rebuild DOCX template

## Form date

Context field `form_date` (not a hardcoded `20` century prefix).

Current product format: day/month as dots, year filled:

`....... / ........ / {YYYY}`

HTML: `{{ form_date }}` with `dir="ltr"` on the date span.
Word: `{{ form_date }}` in template; after `doc.render`, `_fix_registration_docx_bidi(..., form_date=...)` must **preserve** the rendered date (never rewrite to `..../..../20`).

## Bidi

- Rebuild mixed Arabic/Latin cells carefully; keep `w:tc` identity (not `id()`).
- After changing the builder script, regenerate `registration_form_template.docx` or patch placeholders in place.

## Checklist

1. Update HTML + context + bidi fixer together.
2. Rebuild/deploy so Docker serves new templates.
3. Re-print one student form to verify signature dates.
