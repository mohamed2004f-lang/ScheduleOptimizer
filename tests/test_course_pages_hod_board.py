"""لوحة صفحات المقررات لرئيس القسم: خطة + مشتركة للعرض، اعتماد للمالك فقط."""
from __future__ import annotations

import uuid

from backend.core.college_shared_catalog import save_catalog_entry
from backend.services.course_pages import ensure_course_pages_schema


def test_hod_board_includes_plan_and_shared_readonly(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES ('GENERAL', 'عام', 'Gen', 1)"
    )
    gen_id = int(cur.execute("SELECT id FROM departments WHERE code='GENERAL'").fetchone()[0])
    dcode = f"HB{uid}"[:12].upper()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (dcode, "هندسة اختبار صفحات", "Pages"),
    )
    dept_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (dcode,)).fetchone()[0])
    owned = f"مقرر قسم-{uid}"
    shared = f"مقرر مشترك-{uid}"
    cur.execute(
        "INSERT INTO courses (course_name, course_code, owning_department_id, units) VALUES (?, ?, ?, 3)",
        (owned, f"DP{uid[:4]}", dept_id),
    )
    save_catalog_entry(
        db_conn,
        {
            "catalog_key": f"hb_{uid}",
            "share_type": "unified",
            "canonical_course_name": shared,
            "canonical_course_code": f"GS{uid[:3]}",
            "units": 3,
            "requirement_scope": "pre_track",
        },
    )
    pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
    head = f"head_hb_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head, pw, dept_id),
    )
    ensure_course_pages_schema(db_conn)
    cur.execute(
        """
        INSERT INTO course_content_change_requests
            (catalog_page_id, course_name, field_name, proposed_json, note, status, requested_by, created_at)
        VALUES (0, ?, 'objectives', '[]', 'طلب اختبار', 'pending', 'inst', '2026-01-01T00:00:00Z')
        """,
        (shared,),
    )
    db_conn.commit()
    rid = int(cur.execute("SELECT id FROM course_content_change_requests WHERE course_name=?", (shared,)).fetchone()[0])
    try:
        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            board = c.get("/course_pages/hod/board")
            assert board.status_code == 200
            data = board.get_json() or {}
            by_name = {x.get("course_name"): x for x in (data.get("courses") or [])}
            assert owned in by_name
            assert shared in by_name
            assert by_name[owned].get("kind") == "department"
            assert by_name[owned].get("can_manage") is True
            assert by_name[shared].get("kind") == "shared"
            assert by_name[shared].get("can_manage") is False
            reqs = data.get("change_requests") or []
            shared_req = next((x for x in reqs if x.get("course_name") == shared), None)
            assert shared_req is not None
            assert shared_req.get("can_review") is False
            deny = c.post(
                f"/course_pages/hod/change_requests/{rid}/review",
                json={"action": "approve"},
            )
            assert deny.status_code == 403
    finally:
        cur.execute("DELETE FROM course_content_change_requests WHERE id = ?", (rid,))
        cur.execute("DELETE FROM users WHERE username = ?", (head,))
        cur.execute("DELETE FROM courses WHERE course_name IN (?, ?)", (owned, shared))
        cur.execute("DELETE FROM college_shared_catalog WHERE catalog_key = ?", (f"hb_{uid}",))
        cur.execute("DELETE FROM departments WHERE id = ?", (dept_id,))
        db_conn.commit()
