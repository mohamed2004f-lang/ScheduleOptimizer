"""طلبات القسم العام والتسجيلات المتأثرة بمقرر خرج من القوائم المعتمدة."""
from __future__ import annotations

import uuid

from backend.services.term_engine import ensure_term_engine_tables, parse_ops_term
from backend.services.utilities import get_current_term


def _term_key(db_conn) -> str:
    ensure_term_engine_tables(db_conn)
    parsed = parse_ops_term(*get_current_term(conn=db_conn))
    assert parsed
    return parsed["term_key"]


def _make_departments(db_conn, uid: str) -> tuple[int, int]:
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active)"
        " VALUES ('GENERAL', 'القسم العام', 'General', 1)"
    )
    gen_id = int(
        cur.execute("SELECT id FROM departments WHERE UPPER(TRIM(code)) = 'GENERAL'").fetchone()[0]
    )
    code = f"AL{uid[:6]}"
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, 'قسم تنبيهات', 'Alerts', 1)",
        (code,),
    )
    dept_id = int(cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0])
    return gen_id, dept_id


def test_general_requests_summary_flags_unapproved_requests(db_conn):
    from backend.services.term_offering_alerts import general_requests_summary
    from backend.services.term_offerings import _upsert_state, save_offered_courses

    uid = uuid.uuid4().hex[:8]
    gen_id, dept_id = _make_departments(db_conn, uid)
    cur = db_conn.cursor()
    wanted = f"رياضيات طلب {uid}"
    approved = f"فيزياء معتمدة {uid}"
    own = f"مقرر تخصص {uid}"
    for name, code, owner in (
        (wanted, f"R1{uid[:4]}", gen_id),
        (approved, f"R2{uid[:4]}", gen_id),
        (own, f"R3{uid[:4]}", dept_id),
    ):
        cur.execute(
            "INSERT OR REPLACE INTO courses (course_name, course_code, units, owning_department_id)"
            " VALUES (?, ?, 3, ?)",
            (name, code, owner),
        )
    term_key = _term_key(db_conn)
    db_conn.commit()

    save_offered_courses(
        db_conn,
        term_key=term_key,
        course_names=[own, wanted, approved],
        actor="hod-dept",
        department_id=dept_id,
    )
    save_offered_courses(
        db_conn,
        term_key=term_key,
        course_names=[approved],
        actor="hod-gen",
        department_id=gen_id,
    )
    _upsert_state(db_conn, term_key, gen_id, status="published", actor="hod-gen", published=True)
    db_conn.commit()

    summary = general_requests_summary(db_conn, term_key=term_key)
    assert summary["general_published"] is True
    mine = [r for r in summary["rows"] if r["department_id"] == dept_id]
    by_name = {r["course_name"]: r for r in mine}
    assert by_name[wanted]["on_general_list"] is False
    assert by_name[approved]["on_general_list"] is True
    assert own not in by_name
    assert sum(1 for r in mine if not r["on_general_list"]) == 1
    assert summary["missing_count"] >= 1


def test_orphan_registrations_detected_after_general_drops_course(db_conn):
    from backend.services.term_offering_alerts import (
        REASON_GENERAL_DROPPED,
        notify_orphan_registrations,
        orphan_registrations,
    )
    from backend.services.term_offerings import _upsert_state, save_offered_courses

    uid = uuid.uuid4().hex[:8]
    gen_id, dept_id = _make_departments(db_conn, uid)
    cur = db_conn.cursor()
    dropped = f"لغة عامة {uid}"
    kept = f"مقرر باقٍ {uid}"
    for name, code, owner in ((dropped, f"O1{uid[:4]}", gen_id), (kept, f"O2{uid[:4]}", dept_id)):
        cur.execute(
            "INSERT OR REPLACE INTO courses (course_name, course_code, units, owning_department_id)"
            " VALUES (?, ?, 3, ?)",
            (name, code, owner),
        )
    sid = f"ORP{uid[:5]}"
    cur.execute(
        "INSERT INTO students (student_id, student_name, join_year, department_id) VALUES (?, ?, '1445', ?)",
        (sid, "طالب متأثر", dept_id),
    )
    pw = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
    ).fetchone()[0]
    cur.execute(
        "INSERT INTO users (username, password_hash, role, student_id) VALUES (?, ?, 'student', ?)",
        (f"stu-{uid}", pw, sid),
    )
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (f"hod-{uid}", pw, dept_id),
    )
    for cname in (dropped, kept):
        cur.execute(
            "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, '')",
            (sid, cname),
        )
    term_key = _term_key(db_conn)
    db_conn.commit()

    save_offered_courses(
        db_conn,
        term_key=term_key,
        course_names=[kept, dropped],
        actor="hod-dept",
        department_id=dept_id,
    )
    save_offered_courses(
        db_conn,
        term_key=term_key,
        course_names=[],
        actor="hod-gen",
        department_id=gen_id,
    )
    _upsert_state(db_conn, term_key, dept_id, status="published", actor="hod-dept", published=True)
    _upsert_state(db_conn, term_key, gen_id, status="published", actor="hod-gen", published=True)
    db_conn.commit()

    found = orphan_registrations(db_conn, term_key=term_key, department_id=dept_id)
    names = {r["course_name"] for r in found["rows"]}
    assert dropped in names
    assert kept not in names
    assert found["students"] == 1
    assert found["rows"][0]["reason"] == REASON_GENERAL_DROPPED

    result = notify_orphan_registrations(
        db_conn, term_key=term_key, actor="hod-dept", department_id=dept_id, days=7
    )
    assert result["notified_students"] >= 1
    assert result["notified_heads"] >= 1
    assert result["exceptions"] == 2

    ops = {
        r[0]
        for r in db_conn.cursor().execute(
            "SELECT operation FROM term_operation_exceptions WHERE student_id = ? AND status = 'approved'",
            (sid,),
        )
    }
    assert ops == {"drop_course", "add_course"}
    titles = [
        r[0]
        for r in db_conn.cursor().execute(
            "SELECT title FROM notifications WHERE user = ?", (f"stu-{uid}",)
        )
    ]
    assert titles

    again = notify_orphan_registrations(
        db_conn, term_key=term_key, actor="hod-dept", department_id=dept_id, days=7
    )
    assert again["exceptions"] == 0

    db_conn.execute("DELETE FROM registrations WHERE student_id = ?", (sid,))
    db_conn.execute("DELETE FROM students WHERE student_id = ?", (sid,))
    db_conn.commit()


def test_orphans_endpoint_requires_department_writer(app, db_conn):
    c = app.test_client()
    login = c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
    assert login.status_code == 200
    r = c.get("/term_offerings/orphans")
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json() or {}
    assert j.get("status") == "ok"
    assert isinstance(j.get("rows"), list)
