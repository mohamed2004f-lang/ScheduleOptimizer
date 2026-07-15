"""اختبارات توجيه اعتمادات رئيس القسم لقسم عرض المقرر."""
from __future__ import annotations

import uuid

import pytest


def _set_current_term(cur, semester: str = "خريف 44-45") -> str:
    parts = semester.split()
    tname = parts[0] if parts else "خريف"
    tyear = parts[1] if len(parts) > 1 else "44-45"
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', ?)",
        (tname,),
    )
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', ?)",
        (tyear,),
    )
    return semester


def _seed_cross_dept_course(db_conn, uid: str):
    """مقرر بملكية قسم منزل، يُدرَّس في قسم عرض آخر عبر مجموعة تدريس."""
    cur = db_conn.cursor()
    sem = _set_current_term(cur)
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"HO{uid}"[:12].upper(), "منزل", "Home"),
    )
    home_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (f"HO{uid}"[:12].upper(),)).fetchone()[0])
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"TE{uid}"[:12].upper(), "تدريس", "Teach"),
    )
    teach_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (f"TE{uid}"[:12].upper(),)).fetchone()[0])
    cname = f"HodRoute-{uid}"
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
        (cname, "HR101", 3, home_id),
    )
    cur.execute(
        "INSERT OR IGNORE INTO instructors (id, name, type) VALUES (99, 'أستاذ عابر', 'internal')"
    )
    cur.execute(
        """
        INSERT INTO teaching_groups (
            course_name, semester, department_id, group_code, instructor_id, is_active
        ) VALUES (?, ?, ?, 'A', 99, 1)
        """,
        (cname, sem, teach_id),
    )
    tgid = int(cur.execute("SELECT id FROM teaching_groups WHERE course_name=?", (cname,)).fetchone()[0])
    pw = cur.execute("SELECT password_hash FROM users WHERE username='admin-test' LIMIT 1").fetchone()[0]
    home_hod = f"hod_home_{uid}"
    teach_hod = f"hod_teach_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (home_hod, pw, home_id),
    )
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (teach_hod, pw, teach_id),
    )
    cur.execute(
        """
        INSERT INTO grade_drafts (
            semester, course_name, teaching_group_id, instructor_id, status, submitted_at
        ) VALUES (?, ?, ?, 99, 'Submitted', datetime('now'))
        """,
        (sem, cname, tgid),
    )
    draft_id = int(cur.execute("SELECT id FROM grade_drafts WHERE course_name=?", (cname,)).fetchone()[0])
    db_conn.commit()
    return {
        "sem": sem,
        "cname": cname,
        "home_id": home_id,
        "teach_id": teach_id,
        "tgid": tgid,
        "draft_id": draft_id,
        "home_hod": home_hod,
        "teach_hod": teach_hod,
    }


class TestCourseHodRouting:
    def test_hod_may_operate_uses_teaching_group_department(self, db_conn):
        uid = uuid.uuid4().hex[:8]
        ctx = _seed_cross_dept_course(db_conn, uid)
        from backend.core.department_scope_policy import hod_may_operate_on_course

        assert hod_may_operate_on_course(
            db_conn,
            ctx["teach_hod"],
            ctx["cname"],
            teaching_group_id=ctx["tgid"],
            semester=ctx["sem"],
        )
        assert not hod_may_operate_on_course(
            db_conn,
            ctx["home_hod"],
            ctx["cname"],
            teaching_group_id=ctx["tgid"],
            semester=ctx["sem"],
        )

    def test_pending_grade_drafts_filtered_for_hod(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        ctx = _seed_cross_dept_course(db_conn, uid)
        with app.test_client() as c:
            lg = c.post(
                "/auth/login",
                json={"username": ctx["teach_hod"], "password": "TestP@ssw0rd!"},
            )
            assert lg.status_code == 200
            r = c.get("/grades/drafts/pending")
            assert r.status_code == 200
            ids = {d.get("id") for d in (r.get_json() or {}).get("pending") or []}
            assert ctx["draft_id"] in ids

            c.post("/auth/logout")
            lg2 = c.post(
                "/auth/login",
                json={"username": ctx["home_hod"], "password": "TestP@ssw0rd!"},
            )
            assert lg2.status_code == 200
            r2 = c.get("/grades/drafts/pending")
            ids2 = {d.get("id") for d in (r2.get_json() or {}).get("pending") or []}
            assert ctx["draft_id"] not in ids2

    def test_approve_grade_draft_blocked_for_wrong_hod(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        ctx = _seed_cross_dept_course(db_conn, uid)
        with app.test_client() as c:
            lg = c.post(
                "/auth/login",
                json={"username": ctx["home_hod"], "password": "TestP@ssw0rd!"},
            )
            assert lg.status_code == 200
            r = c.post(f"/grades/drafts/{ctx['draft_id']}/approve")
            assert r.status_code == 403
            assert (r.get_json() or {}).get("message") == "FORBIDDEN_DEPARTMENT_SCOPE"

            c.post("/auth/logout")
            lg2 = c.post(
                "/auth/login",
                json={"username": ctx["teach_hod"], "password": "TestP@ssw0rd!"},
            )
            assert lg2.status_code == 200
            cur = db_conn.cursor()
            cur.execute(
                "INSERT INTO grade_draft_items (draft_id, student_id, computed_total) VALUES (?, 'S1', 75)",
                (ctx["draft_id"],),
            )
            db_conn.commit()
            r2 = c.post(f"/grades/drafts/{ctx['draft_id']}/approve")
            assert r2.status_code == 200, r2.get_data(as_text=True)
