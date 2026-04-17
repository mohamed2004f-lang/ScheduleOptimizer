#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tpl = ROOT / "frontend" / "templates"

replacements = {
    "https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.rtl.min.css": "/static/vendor/bootstrap/bootstrap.rtl.min.css",
    "https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js": "/static/vendor/bootstrap/bootstrap.bundle.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css": "/static/vendor/fontawesome/all.min.css",
}

changed = 0
for path in tpl.rglob("*.html"):
    text = path.read_text(encoding="utf-8")
    new = text
    for old, new_val in replacements.items():
        new = new.replace(old, new_val)
    if new != text:
        path.write_text(new, encoding="utf-8")
        changed += 1

print(f"changed_templates={changed}")

