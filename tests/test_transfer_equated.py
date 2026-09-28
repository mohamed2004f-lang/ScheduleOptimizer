"""اختبارات وسم انتقال الطالب ومقررات المعادلة في الكشف."""

from __future__ import annotations

import uuid


def test_save_equated_semester_marks_student_and_grades(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    # ضمان الأعمدة في بيئة PostgreSQL قبل Alembic 0017
    for stmt in (
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS transfer_kind TEXT DEFAULT ''",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS transfer_from_department_id BIGINT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS transfer_from_label TEXT DEFAULT ''",
        "ALTER TABLE grades ADD COLUMN IF NOT EXISTS is_equated INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            cur.execute(stmt)
        except Exception:
            # SQLite قد لا يدعم IF NOT EXISTS بنفس الصيغة
            try:
                cur.execute(stmt.replace(" IF NOT EXISTS", "").replace("BIGINT", "INTEGER"))
            except Exception:
                pass
    db_conn.commit()
    code = f"TR{uid}".upper()[:12]
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (code, "الطاقات", "Energy"),
    )
    src_dept = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
    dest_code = f"DE{uid}".upper()[:12]
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (dest_code, "مدني", "Civil"),
    )
    dest_dept = cur.execute("SELECT id FROM departments WHERE code = ?", (dest_code,)).fetchone()[0]
    sid = f"X{uid}"
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
        (sid, "طالب منتقل", dest_dept),
    )
    cname = f"مقرر-معادل-{uid}"
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
        (cname, f"EQ{uid[:4]}".upper(), 3, dest_dept),
    )
    pw = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
    ).fetchone()[0]
    head_user = f"head_eq_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head_user, pw, dest_dept),
    )
    db_conn.commit()

    with app.test_client() as c:
        assert c.post(
            "/auth/login",
            json={"username": head_user, "password": "TestP@ssw0rd!"},
        ).status_code == 200
        meta = c.get("/grades/transfer_meta")
        assert meta.status_code == 200
        assert any(int(d["id"]) == int(src_dept) for d in (meta.get_json() or {}).get("departments") or [])

        save = c.post(
            "/grades/save",
            json={
                "student_id": sid,
                "semester": "خريف 2024/2025",
                "reason": "إدخال فصل معادلة انتقال داخلي",
                "is_equated_semester": True,
                "transfer": {
                    "kind": "internal",
                    "department_id": src_dept,
                    "label": "الطاقات",
                },
                "grades": [{"course_name": cname, "grade": 72}],
            },
        )
        assert save.status_code == 200, save.get_data(as_text=True)

        tr = c.get(f"/grades/transcript/{sid}")
        assert tr.status_code == 200
        body = tr.get_json() or {}
        transfer = body.get("transfer") or {}
        assert transfer.get("kind") == "internal"
        assert "الطاقات" in (transfer.get("badge") or "")
        assert "خريف 2024/2025" in (body.get("equated_semesters") or [])
        courses = (body.get("transcript") or {}).get("خريف 2024/2025") or []
        assert courses and courses[0].get("is_equated") is True

    row = db_conn.execute(
        "SELECT COALESCE(is_equated,0) FROM grades WHERE student_id=? AND course_name=?",
        (sid, cname),
    ).fetchone()
    assert row is not None
    assert int(row[0]) == 1
