# -*- coding: utf-8 -*-
"""استبعاد الخريجين من قوائم التسجيل التشغيلية."""


def _ensure_enrollment_plans(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS enrollment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            status TEXT NOT NULL,
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


def test_list_plans_excludes_graduated_for_staff(app, db_conn, auth_client):
    cur = db_conn.cursor()
    _ensure_enrollment_plans(cur)
    sid_active = "SGRACT01"
    sid_grad = "SGGRAD01"
    for sid, name, status in (
        (sid_active, "نشط", "active"),
        (sid_grad, "خريج", "graduated"),
    ):
        cur.execute("DELETE FROM enrollment_plans WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM students WHERE student_id = ?", (sid,))
        cur.execute(
            """
            INSERT INTO students (student_id, student_name, enrollment_status)
            VALUES (?, ?, ?)
            """,
            (sid, name, status),
        )
        cur.execute(
            """
            INSERT INTO enrollment_plans (student_id, semester, status, created_at, updated_at)
            VALUES (?, 'خريف 2026/2027', 'Pending', datetime('now'), datetime('now'))
            """,
            (sid,),
        )
    db_conn.commit()

    r = auth_client.get("/enrollment/plans?status=Pending&semester=خريف%202026/2027")
    assert r.status_code == 200, r.data
    plans = (r.get_json() or {}).get("plans") or []
    sids = {str(p.get("student_id") or "") for p in plans}
    assert sid_active in sids
    assert sid_grad not in sids


def test_supervised_students_defaults_to_active_only(app, db_conn):
    from werkzeug.security import generate_password_hash

    cur = db_conn.cursor()
    uname = "sup_alumni_filter"
    cur.execute("DELETE FROM users WHERE username = ?", (uname,))
    cur.execute(
        "DELETE FROM student_supervisor WHERE instructor_id IN "
        "(SELECT id FROM instructors WHERE name = ?)",
        ("مشرف اختبار خريج",),
    )
    cur.execute("DELETE FROM instructors WHERE name = ?", ("مشرف اختبار خريج",))
    cur.execute("INSERT INTO instructors (name) VALUES (?)", ("مشرف اختبار خريج",))
    iid = int(
        cur.execute(
            "SELECT id FROM instructors WHERE name = ?",
            ("مشرف اختبار خريج",),
        ).fetchone()[0]
    )
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, instructor_id, is_supervisor)
        VALUES (?, ?, 'supervisor', ?, 1)
        """,
        (uname, generate_password_hash("Passw0rd!"), iid),
    )
    for sid, status in (("SALUM01", "graduated"), ("SACT01", "active")):
        cur.execute("DELETE FROM student_supervisor WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM students WHERE student_id = ?", (sid,))
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status) VALUES (?, ?, ?)",
            (sid, sid, status),
        )
        cur.execute(
            "INSERT INTO student_supervisor (student_id, instructor_id) VALUES (?, ?)",
            (sid, iid),
        )
    db_conn.commit()

    with app.test_client() as client:
        login = client.post(
            "/auth/login",
            json={"username": uname, "password": "Passw0rd!"},
        )
        assert login.status_code == 200, login.get_data(as_text=True)

        r = client.get("/instructors/supervised_students")
        assert r.status_code == 200, r.data
        students = (r.get_json() or {}).get("students") or []
        sids = {str(s.get("student_id") or "") for s in students}
        assert "SACT01" in sids
        assert "SALUM01" not in sids

        r2 = client.get("/instructors/supervised_students?include_inactive=1")
        sids2 = {
            str(s.get("student_id") or "")
            for s in ((r2.get_json() or {}).get("students") or [])
        }
        assert "SALUM01" in sids2


def test_load_supervised_students_excludes_alumni(db_conn):
    from backend.services.supervisor_portal import _load_supervised_students

    cur = db_conn.cursor()
    cur.execute("DELETE FROM instructors WHERE name = ?", ("مشرف بوابة خريج",))
    cur.execute("INSERT INTO instructors (name) VALUES (?)", ("مشرف بوابة خريج",))
    iid = int(
        cur.execute(
            "SELECT id FROM instructors WHERE name = ?",
            ("مشرف بوابة خريج",),
        ).fetchone()[0]
    )
    for sid, status in (("SPALUM1", "graduated"), ("SPACT1", "active")):
        cur.execute("DELETE FROM student_supervisor WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM students WHERE student_id = ?", (sid,))
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status) VALUES (?, ?, ?)",
            (sid, sid, status),
        )
        cur.execute(
            "INSERT INTO student_supervisor (student_id, instructor_id) VALUES (?, ?)",
            (sid, iid),
        )
    db_conn.commit()
    rows = _load_supervised_students(db_conn, iid)
    sids = {r["student_id"] for r in rows}
    assert "SPACT1" in sids
    assert "SPALUM1" not in sids
