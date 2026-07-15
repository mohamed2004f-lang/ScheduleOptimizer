"""اختبارات نشر الدرجات وحزمة القسم."""

import uuid

from backend.services.grade_publication import (
    build_hod_final_batch_summary,
    ensure_grade_publication_schema,
    hod_approve_final_draft,
    submit_department_batch_to_dean,
)

DEPT_FINAL = 88
INSTRUCTOR_FINAL = 8801
HOD_FINAL = "hod-g88"


def _hod_password(db_conn) -> str:
    row = db_conn.execute(
        "SELECT password_hash FROM users WHERE username='admin-test'"
    ).fetchone()
    return row[0]


def _seed_grade_workflow(db_conn, uid: str | None = None):
    uid = uid or uuid.uuid4().hex[:6]
    cname = f"فيزياء-{uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (id, code, name_ar) VALUES (?, 'T88', 'قسم اختبار')",
        (DEPT_FINAL,),
    )
    cur.execute(
        "INSERT OR IGNORE INTO students (student_id, student_name) VALUES ('S010', 'طالب عشرة')"
    )
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, 'PHY5', 3)",
        (cname,),
    )
    cur.execute(
        "INSERT OR IGNORE INTO registrations (student_id, course_name) VALUES ('S010', ?)",
        (cname,),
    )
    cur.execute(
        "INSERT OR IGNORE INTO instructors (id, name, department_id) VALUES (?, 'أستاذ نهائي', ?)",
        (INSTRUCTOR_FINAL, DEPT_FINAL),
    )
    pw = _hod_password(db_conn)
    cur.execute(
        """
        INSERT OR IGNORE INTO users (username, password_hash, role, department_id)
        VALUES (?, ?, 'head_of_department', ?)
        """,
        (HOD_FINAL, pw, DEPT_FINAL),
    )
    cur.execute(
        """
        INSERT INTO teaching_groups (course_name, semester, department_id, group_code, instructor_id, is_active)
        VALUES (?, 'خريف 44-45', ?, ?, ?, 1)
        """,
        (cname, DEPT_FINAL, f"A{uid}"[:8], INSTRUCTOR_FINAL),
    )
    tgid = int(
        cur.execute(
            "SELECT id FROM teaching_groups WHERE course_name=? AND group_code=?",
            (cname, f"A{uid}"[:8]),
        ).fetchone()[0]
    )
    cur.execute(
        """
        INSERT INTO grade_drafts
            (semester, course_name, section_id, instructor_id, teaching_group_id,
             draft_phase, status, submitted_at)
        VALUES ('خريف 44-45', ?, 1, ?, ?, 'final', 'Submitted', datetime('now'))
        """,
        (cname, INSTRUCTOR_FINAL, tgid),
    )
    draft_id = int(
        cur.execute("SELECT id FROM grade_drafts WHERE course_name=?", (cname,)).fetchone()[0]
    )
    cur.execute(
        """
        INSERT INTO grade_draft_items
            (draft_id, student_id, coursework, midterm, final_exam, computed_total)
        VALUES (?, 'S010', 30, 20, 40, 90)
        """,
        (draft_id,),
    )
    db_conn.commit()
    return draft_id, cname


def test_hod_approve_final_internal_only(app, db_conn):
    draft_id, cname = _seed_grade_workflow(db_conn)
    with app.test_client() as c:
        assert (
            c.post(
                "/auth/login",
                json={"username": HOD_FINAL, "password": "TestP@ssw0rd!"},
            ).status_code
            == 200
        )
        r = c.post(f"/grades/drafts/{draft_id}/approve")
        assert r.status_code == 200
        body = r.get_json()
        assert body.get("hod_approved") is True
    row = db_conn.execute(
        "SELECT grade FROM grades WHERE student_id='S010' AND course_name=?", (cname,)
    ).fetchone()
    assert row is None


def test_partial_publish_and_batch_flow(app, db_conn):
    uid = uuid.uuid4().hex[:6]
    pname = f"جزئي-{uid}"
    dept_partial = 5
    instructor_partial = 505
    hod_partial = "hod-g5"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (id, code, name_ar) VALUES (?, 'ME5', 'ميكانيك')",
        (dept_partial,),
    )
    cur.execute(
        "INSERT OR IGNORE INTO instructors (id, name, department_id) VALUES (?, 'أستاذ جزئي', ?)",
        (instructor_partial, dept_partial),
    )
    pw = _hod_password(db_conn)
    cur.execute(
        """
        INSERT OR IGNORE INTO users (username, password_hash, role, department_id)
        VALUES (?, ?, 'head_of_department', ?)
        """,
        (hod_partial, pw, dept_partial),
    )
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, 'P1', 3)",
        (pname,),
    )
    cur.execute(
        """
        INSERT INTO teaching_groups (course_name, semester, department_id, group_code, instructor_id, is_active)
        VALUES (?, 'خريف 44-45', ?, ?, ?, 1)
        """,
        (pname, dept_partial, f"P{uid}"[:8], instructor_partial),
    )
    tgid = int(
        cur.execute(
            "SELECT id FROM teaching_groups WHERE course_name=? AND group_code=?",
            (pname, f"P{uid}"[:8]),
        ).fetchone()[0]
    )
    cur.execute(
        """
        INSERT INTO grade_drafts
            (semester, course_name, section_id, instructor_id, teaching_group_id, draft_phase, status)
        VALUES ('خريف 44-45', ?, 2, ?, ?, 'partial', 'Draft')
        """,
        (pname, instructor_partial, tgid),
    )
    pid = int(cur.execute("SELECT id FROM grade_drafts WHERE course_name=?", (pname,)).fetchone()[0])
    cur.execute(
        "INSERT INTO grade_draft_items (draft_id, student_id, coursework, midterm) VALUES (?, 'S010', 25, 15)",
        (pid,),
    )
    db_conn.commit()

    with app.test_client() as c:
        assert (
            c.post(
                "/auth/login",
                json={"username": hod_partial, "password": "TestP@ssw0rd!"},
            ).status_code
            == 200
        )
        pr = c.post(f"/grades/drafts/{pid}/publish_partial")
        assert pr.status_code == 200

    ensure_grade_publication_schema(db_conn)
    row = db_conn.execute(
        "SELECT partial_total FROM student_published_grades WHERE student_id='S010' AND visibility='partial'"
    ).fetchone()
    assert row and float(row[0]) == 40.0


def test_dean_publish_batch(app, db_conn):
    draft_id, cname = _seed_grade_workflow(db_conn)
    with app.test_request_context():
        from flask import session

        session["user_role"] = "head_of_department"
        session["user"] = HOD_FINAL
        session["username"] = HOD_FINAL
        hod_approve_final_draft(db_conn, draft_id)
    summary = build_hod_final_batch_summary(
        db_conn, department_id=DEPT_FINAL, semester="خريف 44-45", actor=HOD_FINAL
    )
    assert summary["ready_courses"] >= 1
    assert summary["completion_percent"] == 100.0
    with app.test_request_context():
        from flask import session

        session["user_role"] = "head_of_department"
        session["user"] = HOD_FINAL
        sub = submit_department_batch_to_dean(
            db_conn, department_id=DEPT_FINAL, semester="خريف 44-45", actor=HOD_FINAL
        )
    assert sub.get("ok") is True
    batch_id = sub["batch_id"]
    with app.test_client() as c:
        assert (
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            ).status_code
            == 200
        )
        pub = c.post(f"/grades/dean/final_batches/{batch_id}/publish")
        assert pub.status_code == 200
    row = db_conn.execute(
        "SELECT grade FROM grades WHERE student_id='S010' AND course_name=?", (cname,)
    ).fetchone()
    assert row and float(row[0]) == 90.0
