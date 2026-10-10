"""تحديث فصل موجود بدل إنشاء مكرر + ملخص التغييرات."""
from __future__ import annotations

import uuid

from backend.services.grades import (
    _build_grades_save_changes,
    _move_student_semester,
    _upsert_semester_scope,
    apply_grades_batch,
)


def _seed_student_semester(db_conn, *, semester: str = "خريف 2021/2022"):
    uid = uuid.uuid4().hex[:8]
    sid = f"E{uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) "
        "VALUES ('GENERAL', 'عام', 'Gen', 1)"
    )
    dcode = f"D{uid}"[:12].upper()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (dcode, "مدني", "Civ"),
    )
    dept_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (dcode,)).fetchone()[0])
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
        (sid, "طالب تعديل", dept_id),
    )
    c1, c2 = f"مقررأ-{uid}", f"مقررب-{uid}"
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units) VALUES (?, ?, ?)",
        (c1, f"A{uid[:4].upper()}", 3),
    )
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units) VALUES (?, ?, ?)",
        (c2, f"B{uid[:4].upper()}", 2),
    )
    db_conn.commit()
    apply_grades_batch(
        db_conn,
        sid,
        semester,
        [
            {"course_name": c1, "course_code": f"A{uid[:4].upper()}", "grade": 40},
            {"course_name": c2, "course_code": f"B{uid[:4].upper()}", "grade": 55},
        ],
        "seed",
    )
    db_conn.commit()
    return {
        "sid": sid,
        "dept_id": dept_id,
        "semester": semester,
        "c1": c1,
        "c2": c2,
        "code1": f"A{uid[:4].upper()}",
        "code2": f"B{uid[:4].upper()}",
        "uid": uid,
    }


def test_grade_edit_inplace_no_duplicate_semester(db_conn):
    ctx = _seed_student_semester(db_conn)
    apply_grades_batch(
        db_conn,
        ctx["sid"],
        ctx["semester"],
        [
            {"course_name": ctx["c1"], "course_code": ctx["code1"], "grade": 70},
            {"course_name": ctx["c2"], "course_code": ctx["code2"], "grade": 55},
        ],
        "edit",
    )
    db_conn.commit()
    rows = db_conn.cursor().execute(
        "SELECT DISTINCT semester FROM grades WHERE student_id=?",
        (ctx["sid"],),
    ).fetchall()
    assert len(rows) == 1
    assert (rows[0][0] if not hasattr(rows[0], "keys") else rows[0]["semester"]) == ctx["semester"]
    g = db_conn.cursor().execute(
        "SELECT grade FROM grades WHERE student_id=? AND semester=? AND course_name=?",
        (ctx["sid"], ctx["semester"], ctx["c1"]),
    ).fetchone()
    assert float(g[0] if not hasattr(g, "keys") else g["grade"]) == 70.0


def test_rename_moves_student_semester_only(db_conn):
    ctx = _seed_student_semester(db_conn)
    # طالب آخر بنفس الفصل القديم — يجب ألا يتأثر
    other = f"O{ctx['uid']}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
        (other, "آخر", ctx["dept_id"]),
    )
    db_conn.commit()
    apply_grades_batch(
        db_conn,
        other,
        ctx["semester"],
        [{"course_name": ctx["c1"], "course_code": ctx["code1"], "grade": 90}],
        "other",
    )
    db_conn.commit()

    new_sem = "خريف 2022/2023"
    info = _move_student_semester(db_conn, ctx["sid"], ctx["semester"], new_sem)
    db_conn.commit()
    assert info["moved"] is True

    mine = {
        (r[0] if not hasattr(r, "keys") else r["semester"])
        for r in db_conn.cursor().execute(
            "SELECT DISTINCT semester FROM grades WHERE student_id=?", (ctx["sid"],)
        ).fetchall()
    }
    assert mine == {new_sem}

    other_sems = {
        (r[0] if not hasattr(r, "keys") else r["semester"])
        for r in db_conn.cursor().execute(
            "SELECT DISTINCT semester FROM grades WHERE student_id=?", (other,)
        ).fetchall()
    }
    assert other_sems == {ctx["semester"]}


def test_rename_rejects_course_conflict(db_conn):
    ctx = _seed_student_semester(db_conn)
    new_sem = "ربيع 2021/2022"
    apply_grades_batch(
        db_conn,
        ctx["sid"],
        new_sem,
        [{"course_name": ctx["c1"], "course_code": ctx["code1"], "grade": 10}],
        "conflict",
    )
    db_conn.commit()
    try:
        _move_student_semester(db_conn, ctx["sid"], ctx["semester"], new_sem)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "لا يمكن نقل الفصل" in str(e)


def test_build_changes_summary_grade_add_scope(db_conn):
    ctx = _seed_student_semester(db_conn)
    _upsert_semester_scope(
        db_conn,
        ctx["sid"],
        ctx["semester"],
        {"scope_kind": "college_general"},
    )
    db_conn.commit()

    c3 = f"مقررجديد-{ctx['uid']}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units) VALUES (?, ?, ?)",
        (c3, f"C{ctx['uid'][:4].upper()}", 2),
    )
    db_conn.commit()

    changes = _build_grades_save_changes(
        db_conn,
        ctx["sid"],
        ctx["semester"],
        [
            {"course_name": ctx["c1"], "course_code": ctx["code1"], "grade": 41},
            {"course_name": ctx["c2"], "course_code": ctx["code2"], "grade": 55},
            {"course_name": c3, "course_code": f"C{ctx['uid'][:4].upper()}", "grade": 80},
        ],
        semester_scope={
            "scope_kind": "department",
            "department_id": ctx["dept_id"],
            "department_label": "الهندسة المدنية",
            "group_code": "",
        },
        rename_info={"moved": False},
    )
    assert c3 in changes["courses_added"]
    assert any(x.get("course_name") == ctx["c1"] for x in changes["grades_changed"])
    assert changes["scope_changed"] is not None
    assert changes["scope_changed"]["from"] == "اتجاه عام"
    assert "مدني" in changes["scope_changed"]["to"] or "قسم" in changes["scope_changed"]["to"]


def test_save_grades_api_with_source_semester(app, db_conn):
    ctx = _seed_student_semester(db_conn)
    cur = db_conn.cursor()
    pw = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
    ).fetchone()[0]
    head = f"head_ip_{ctx['uid']}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head, pw, ctx["dept_id"]),
    )
    db_conn.commit()

    new_sem = "خريف 2020/2021"
    with app.test_client() as client:
        assert client.post("/auth/login", json={"username": head, "password": "TestP@ssw0rd!"}).status_code == 200
        r = client.post(
            "/grades/save",
            json={
                "student_id": ctx["sid"],
                "semester": new_sem,
                "source_semester": ctx["semester"],
                "reason": "تصحيح تسمية الفصل والسنة",
                "grades": [
                    {"course_name": ctx["c1"], "course_code": ctx["code1"], "grade": 40},
                    {"course_name": ctx["c2"], "course_code": ctx["code2"], "grade": 55},
                ],
                "semester_scope": {"scope_kind": "college_general"},
            },
        )
        assert r.status_code == 200, r.get_json()
        body = r.get_json() or {}
        changes = body.get("changes") or {}
        assert changes.get("semester_renamed")
        assert changes["semester_renamed"]["from"] == ctx["semester"]
        assert changes["semester_renamed"]["to"] == new_sem

    sems = {
        (row[0] if not hasattr(row, "keys") else row["semester"])
        for row in db_conn.cursor().execute(
            "SELECT DISTINCT semester FROM grades WHERE student_id=?", (ctx["sid"],)
        ).fetchall()
    }
    assert sems == {new_sem}
