#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402


def set_session(client, *, role: str, instructor_id: int = 2, is_supervisor: int = 0):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "smoke-user"
        sess["user_role"] = role
        sess["instructor_id"] = instructor_id
        sess["is_supervisor"] = is_supervisor


def check(label: str, ok: bool, detail: str = ""):
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {label}" + (f" :: {detail}" if detail else ""))
    return ok


def main() -> int:
    ok_all = True
    app.testing = True
    with app.test_client() as c:
        # Instructor mode
        set_session(c, role="instructor", instructor_id=2, is_supervisor=0)
        r = c.get("/grade_drafts")
        body = r.get_data(as_text=True)
        ok_all &= check("GET /grade_drafts (instructor)", r.status_code == 200, f"status={r.status_code}")
        ok_all &= check("page_mode=instructor", 'window.PAGE_MODE = "instructor"' in body or "window.PAGE_MODE = 'instructor'" in body)

        courses = c.get("/grades/drafts/courses")
        ok_all &= check("GET /grades/drafts/courses", courses.status_code == 200, f"status={courses.status_code}")
        cj = courses.get_json(silent=True) or {}
        sections = cj.get("sections") or []
        ok_all &= check("draft courses payload", isinstance(sections, list), f"sections={len(sections) if isinstance(sections, list) else 'n/a'}")

        mine = c.get("/grades/drafts/mine")
        ok_all &= check("GET /grades/drafts/mine", mine.status_code == 200, f"status={mine.status_code}")

        # Probe roster using first section if present
        if sections:
            first = sections[0] or {}
            course_name = first.get("course_name") or ""
            section_id = first.get("section_id")
            rr = c.get(f"/grades/drafts/roster?course_name={course_name}&section_id={section_id}")
            ok_all &= check("GET /grades/drafts/roster", rr.status_code == 200, f"status={rr.status_code}")

        # Head of department linked to same instructor_id should show both mode
        set_session(c, role="head_of_department", instructor_id=2, is_supervisor=0)
        r2 = c.get("/grade_drafts")
        body2 = r2.get_data(as_text=True)
        ok_all &= check("GET /grade_drafts (head_of_department)", r2.status_code == 200, f"status={r2.status_code}")
        ok_all &= check("page_mode=both", 'window.PAGE_MODE = "both"' in body2 or "window.PAGE_MODE = 'both'" in body2)

    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())

