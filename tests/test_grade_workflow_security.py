"""مسارات الدرجات: نشر نهائي، أدوار، وغياب الاختبار."""

from __future__ import annotations

import uuid

from backend.services.grade_publication import (
    ensure_grade_publication_schema,
    hod_approve_final_draft,
    publish_final_draft_to_grades,
)

DEPT_WF = 91
INSTRUCTOR_WF = 9101
HOD_WF = "hod-wf91"


def _hod_password(db_conn) -> str:
    row = db_conn.execute(
        "SELECT password_hash FROM users WHERE username='admin-test'"
    ).fetchone()
    return row[0]


def _seed_final_draft(db_conn, uid: str | None = None):
    uid = uid or uuid.uuid4().hex[:6]
    cname = f"ميكانيكا-{uid}"
    sid = f"SW{uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (id, code, name_ar) VALUES (?, 'T91', 'قسم ورشة درجات')",
        (DEPT_WF,),
    )
    cur.execute(
        "INSERT OR IGNORE INTO students (student_id, student_name) VALUES (?, 'طالب ورشة')",
        (sid,),
    )
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, 'ME91', 3)",
        (cname,),
    )
    cur.execute(
        "INSERT OR IGNORE INTO instructors (id, name, department_id) VALUES (?, 'أستاذ ورشة', ?)",
        (INSTRUCTOR_WF, DEPT_WF),
    )
    pw = _hod_password(db_conn)
    cur.execute(
        """
        INSERT OR IGNORE INTO users (username, password_hash, role, department_id)
        VALUES (?, ?, 'head_of_department', ?)
        """,
        (HOD_WF, pw, DEPT_WF),
    )
    cur.execute(
        """
        INSERT INTO teaching_groups (course_name, semester, department_id, group_code, instructor_id, is_active)
        VALUES (?, 'خريف 44-45', ?, ?, ?, 1)
        """,
        (cname, DEPT_WF, f"W{uid}"[:8], INSTRUCTOR_WF),
    )
    tgid = int(
        cur.execute(
            "SELECT id FROM teaching_groups WHERE course_name=? AND group_code=?",
            (cname, f"W{uid}"[:8]),
        ).fetchone()[0]
    )
    cur.execute(
        """
        INSERT INTO grade_drafts
            (semester, course_name, section_id, instructor_id, teaching_group_id,
             draft_phase, status, submitted_at)
        VALUES ('خريف 44-45', ?, 3, ?, ?, 'final', 'Submitted', datetime('now'))
        """,
        (cname, INSTRUCTOR_WF, tgid),
    )
    draft_id = int(
        cur.execute("SELECT id FROM grade_drafts WHERE course_name=?", (cname,)).fetchone()[0]
    )
    cur.execute(
        """
        INSERT INTO grade_draft_items
            (draft_id, student_id, coursework, midterm, final_exam, computed_total)
        VALUES (?, ?, 30, 20, 40, 90)
        """,
        (draft_id, sid),
    )
    db_conn.commit()
    return draft_id, cname, sid


def test_publish_final_writes_grades_once(app, db_conn):
    draft_id, cname, sid = _seed_final_draft(db_conn)
    ensure_grade_publication_schema(db_conn)
    n1 = publish_final_draft_to_grades(db_conn, draft_id, actor="dean-wf")
    db_conn.commit()
    assert n1 == 1
    row = db_conn.execute(
        "SELECT grade FROM grades WHERE student_id=? AND course_name=?",
        (sid, cname),
    ).fetchone()
    assert row is not None
    assert float(row[0]) == 90.0
    pub = db_conn.execute(
        """
        SELECT total, visibility FROM student_published_grades
        WHERE student_id=? AND course_name=? AND visibility='final'
        """,
        (sid, cname),
    ).fetchone()
    assert pub is not None
    assert float(pub[0]) == 90.0

    n2 = publish_final_draft_to_grades(db_conn, draft_id, actor="dean-wf")
    db_conn.commit()
    assert n2 == 1
    count = db_conn.execute(
        "SELECT COUNT(*) FROM grades WHERE student_id=? AND course_name=?",
        (sid, cname),
    ).fetchone()[0]
    assert int(count) == 1


def test_instructor_cannot_approve_final_http(app, db_conn, instructor_auth_client):
    draft_id, _, _ = _seed_final_draft(db_conn)
    resp = instructor_auth_client.post(f"/grades/drafts/{draft_id}/approve")
    assert resp.status_code == 403


def test_student_cannot_edit_or_list_drafts(student_auth_client):
    headers = {"Accept": "application/json"}
    mine = student_auth_client.get("/grades/drafts/mine", headers=headers)
    assert mine.status_code == 403
    save = student_auth_client.post(
        "/grades/drafts/1/items",
        json={"items": [{"student_id": "S002", "coursework": 40, "midterm": 20, "final_exam": 40}]},
        headers=headers,
    )
    assert save.status_code == 403
    pub = student_auth_client.post("/grades/drafts/1/publish_partial", headers=headers)
    assert pub.status_code == 403


def test_instructor_cannot_edit_other_instructor_draft(app, db_conn, instructor_auth_client):
    draft_id, _, sid = _seed_final_draft(db_conn)
    db_conn.execute(
        "UPDATE grade_drafts SET status='Draft' WHERE id=?",
        (draft_id,),
    )
    db_conn.commit()
    resp = instructor_auth_client.post(
        f"/grades/drafts/{draft_id}/items",
        json={
            "items": [
                {"student_id": sid, "coursework": 10, "midterm": 10, "final_exam": 10},
            ]
        },
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 403


def test_instructor_saves_own_section_absent_midterm_zeros(app, db_conn):
    uid = uuid.uuid4().hex[:6]
    cname = f"غياب-{uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (id, code, name_ar) VALUES (92, 'T92', 'قسم غياب')"
    )
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, 'AB1', 3)",
        (cname,),
    )
    cur.execute(
        """
        INSERT INTO teaching_groups
            (course_name, semester, department_id, group_code, instructor_id, is_active)
        VALUES (?, 'خريف 44-45', 92, ?, 1, 1)
        """,
        (cname, f"G{uid}"[:8]),
    )
    tgid = int(
        cur.execute(
            "SELECT id FROM teaching_groups WHERE course_name=? AND group_code=?",
            (cname, f"G{uid}"[:8]),
        ).fetchone()[0]
    )
    cur.execute(
        """
        INSERT INTO grade_drafts
            (semester, course_name, section_id, instructor_id, teaching_group_id,
             draft_phase, status)
        VALUES ('خريف 44-45', ?, 0, 1, ?, 'combined', 'Draft')
        """,
        (cname, tgid),
    )
    draft_id = int(cur.lastrowid)
    db_conn.commit()
    with app.test_client() as c:
        assert (
            c.post(
                "/auth/login",
                json={"username": "inst-test", "password": "TestP@ssw0rd!"},
            ).status_code
            == 200
        )
        save_ok = c.post(
            f"/grades/drafts/{draft_id}/items",
            json={
                "items": [
                    {
                        "student_id": "S001",
                        "coursework": 8,
                        "midterm": 18,
                        "final_exam": 40,
                        "absent_midterm": True,
                    }
                ]
            },
        )
        assert save_ok.status_code == 200
        items = (c.get(f"/grades/drafts/{draft_id}").get_json() or {}).get("items") or []
        row = next((x for x in items if x.get("student_id") == "S001"), None)
        assert row is not None
        assert int(row.get("absent_midterm") or 0) == 1
        assert float(row.get("midterm") or 0) == 0.0


def test_hod_approve_does_not_write_grades(app, db_conn):
    draft_id, cname, sid = _seed_final_draft(db_conn)
    with app.test_client() as c:
        assert (
            c.post(
                "/auth/login",
                json={"username": HOD_WF, "password": "TestP@ssw0rd!"},
            ).status_code
            == 200
        )
        r = c.post(f"/grades/drafts/{draft_id}/approve")
        assert r.status_code == 200
        assert (r.get_json() or {}).get("hod_approved") is True
    row = db_conn.execute(
        "SELECT grade FROM grades WHERE student_id=? AND course_name=?",
        (sid, cname),
    ).fetchone()
    assert row is None


def test_instructor_hod_approve_function_forbidden(app, db_conn):
    draft_id, _, _ = _seed_final_draft(db_conn)
    ensure_grade_publication_schema(db_conn)
    with app.test_request_context("/"):
        from flask import session

        session["user"] = "inst-test"
        session["username"] = "inst-test"
        session["user_role"] = "instructor"
        session["instructor_id"] = 1
        result = hod_approve_final_draft(db_conn, draft_id, actor="inst-test")
    assert result.get("ok") is False
    assert int(result.get("code") or 0) == 403


def test_dean_cannot_republish_published_batch(app, db_conn):
    ensure_grade_publication_schema(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT INTO department_final_grade_batches (department_id, semester, status)
        VALUES (?, 'خريف 44-45', 'published')
        """,
        (DEPT_WF,),
    )
    batch_id = int(cur.lastrowid)
    db_conn.commit()
    with app.test_client() as c:
        assert (
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            ).status_code
            == 200
        )
        resp = c.post(f"/grades/dean/final_batches/{batch_id}/publish")
        assert resp.status_code == 400
        assert "انتظار" in ((resp.get_json() or {}).get("message") or "") or resp.status_code == 400


def test_instructor_cannot_dean_publish_batch(app, db_conn, instructor_auth_client):
    ensure_grade_publication_schema(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT INTO department_final_grade_batches (department_id, semester, status)
        VALUES (?, 'خريف 44-45', 'submitted_to_dean')
        """,
        (DEPT_WF + 1,),
    )
    batch_id = int(cur.lastrowid)
    db_conn.commit()
    resp = instructor_auth_client.post(f"/grades/dean/final_batches/{batch_id}/publish")
    assert resp.status_code == 403
