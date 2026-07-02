"""تصحيح الرقم الدراسي — المسؤول الرئيسي والعميد."""

from __future__ import annotations

import uuid


class TestStudentIdRename:
    def test_admin_main_renames_student_id(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        old_sid = f"SO{uid}"
        new_sid = f"SN{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status) VALUES (?, ?, 'active')",
            (old_sid, "طالب تصحيح رقم"),
        )
        cur.execute(
            "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
            (old_sid, "مقرر اختبار"),
        )
        db_conn.commit()

        with app.test_client() as c:
            assert c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            ).status_code == 200
            resp = c.post(
                "/students/student_id/rename",
                json={"old_student_id": old_sid, "new_student_id": new_sid},
            )
            assert resp.status_code == 200, resp.get_data(as_text=True)
            body = resp.get_json() or {}
            assert body.get("new_student_id") == new_sid

            lst = c.get(f"/students/list?_={uid}")
            listed = {x.get("student_id") for x in (lst.get_json() or [])}
            assert new_sid in listed
            assert old_sid not in listed

        reg = cur.execute(
            "SELECT student_id FROM registrations WHERE course_name = ?",
            ("مقرر اختبار",),
        ).fetchone()
        assert reg[0] == new_sid

    def test_head_of_department_forbidden(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        code = f"RH{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "قسم", "Dept"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        old_sid = f"SH{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status) VALUES (?, ?, 'active')",
            (old_sid, "طالب"),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_rn_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, int(dept_id)),
        )
        db_conn.commit()

        with app.test_client() as c:
            assert c.post(
                "/auth/login",
                json={"username": head_user, "password": "TestP@ssw0rd!"},
            ).status_code == 200
            resp = c.post(
                "/students/student_id/rename",
                json={"old_student_id": old_sid, "new_student_id": f"SX{uid}"},
            )
            assert resp.status_code == 403
