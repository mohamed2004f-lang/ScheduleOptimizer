"""خطط التسجيل: فصل حالي مقابل فصول سابقة + أرشفة عند إعادة التفعيل."""
from __future__ import annotations

import uuid

from backend.core.services import StudentService
from backend.services.enrollment import (
    archive_enrollment_plans_not_matching_current_term,
    plan_semester_is_current,
)
from backend.services.term_engine import current_term_match_context


def _ensure_plan_tables(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS enrollment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Draft',
            rejection_reason TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS enrollment_plan_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            course_name TEXT NOT NULL
        )
        """
    )
    db_conn.commit()


def test_archive_stale_plans_keeps_current_term(db_conn, app):
    _ensure_plan_tables(db_conn)
    uid = uuid.uuid4().hex[:8]
    sid = f"S{uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO students (student_id, student_name, enrollment_status) VALUES (?, ?, 'active')",
        (sid, f"Stu {uid}"),
    )
    ctx = current_term_match_context(db_conn)
    current_label = (ctx or {}).get("ops_label") or "خريف 2026/2027"
    cur.execute(
        """
        INSERT INTO enrollment_plans (student_id, semester, status, created_at, updated_at)
        VALUES (?, ?, 'Approved', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (sid, "ربيع 25-26"),
    )
    old_id = int(cur.lastrowid)
    cur.execute(
        """
        INSERT INTO enrollment_plans (student_id, semester, status, created_at, updated_at)
        VALUES (?, ?, 'Draft', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (sid, current_label),
    )
    new_id = int(cur.lastrowid)
    db_conn.commit()

    n = archive_enrollment_plans_not_matching_current_term(db_conn, sid)
    db_conn.commit()
    assert n >= 1
    old = cur.execute("SELECT status FROM enrollment_plans WHERE id = ?", (old_id,)).fetchone()[0]
    new = cur.execute("SELECT status FROM enrollment_plans WHERE id = ?", (new_id,)).fetchone()[0]
    assert old == "Archived"
    assert new == "Draft"
    assert plan_semester_is_current(db_conn, current_label) is True
    assert plan_semester_is_current(db_conn, "ربيع 25-26") is False


def test_reactivate_active_archives_prior_approved_plan(app, db_conn):
    _ensure_plan_tables(db_conn)
    uid = uuid.uuid4().hex[:8]
    sid = f"R{uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO students (student_id, student_name, enrollment_status) VALUES (?, ?, 'suspended')",
        (sid, f"Return {uid}"),
    )
    cur.execute(
        """
        INSERT INTO enrollment_plans (student_id, semester, status, created_at, updated_at)
        VALUES (?, 'ربيع 25-26', 'Approved', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (sid,),
    )
    plan_id = int(cur.lastrowid)
    db_conn.commit()

    result = StudentService.update_enrollment_status(student_id=sid, status="active", reason="عودة")
    assert result.get("status") == "ok"
    assert int(result.get("archived_stale_plans") or 0) >= 1
    st = cur.execute("SELECT status FROM enrollment_plans WHERE id = ?", (plan_id,)).fetchone()[0]
    assert st == "Archived"


def test_student_plans_api_marks_is_current_term(app, db_conn):
    _ensure_plan_tables(db_conn)
    uid = uuid.uuid4().hex[:8]
    sid = f"P{uid}"
    cur = db_conn.cursor()
    pw = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
    ).fetchone()[0]
    cur.execute(
        "INSERT INTO students (student_id, student_name, enrollment_status) VALUES (?, ?, 'active')",
        (sid, f"Portal {uid}"),
    )
    stu_user = f"stu_plan_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, student_id) VALUES (?, ?, 'student', ?)",
        (stu_user, pw, sid),
    )
    ctx = current_term_match_context(db_conn)
    current_label = (ctx or {}).get("ops_label") or "خريف 2026/2027"
    cur.execute(
        """
        INSERT INTO enrollment_plans (student_id, semester, status, created_at, updated_at)
        VALUES (?, 'ربيع 25-26', 'Approved', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (sid,),
    )
    cur.execute(
        """
        INSERT INTO enrollment_plans (student_id, semester, status, created_at, updated_at)
        VALUES (?, ?, 'Draft', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (sid, current_label),
    )
    db_conn.commit()

    with app.test_client() as c:
        assert c.post("/auth/login", json={"username": stu_user, "password": "TestP@ssw0rd!"}).status_code == 200
        with c.session_transaction() as sess:
            sess["student_id"] = sid
            sess["user_role"] = "student"
        r = c.get("/enrollment/plans")
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json() or {}
        plans = data.get("plans") or []
        # خطة ربيع السابقة يجب أن تُؤرشف بالشفاء الكسول ولا تظهر كنشطة
        active = [p for p in plans if p.get("status") != "Archived"]
        assert all(p.get("is_current_term") for p in active)
        assert not any(
            (p.get("semester") or "").startswith("ربيع") and p.get("status") == "Approved"
            for p in plans
        )
