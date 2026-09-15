"""اختبارات ربط القسم عند إضافة طالب يدوياً (نفس نطاق استيراد Excel)."""

from __future__ import annotations

import uuid


class TestStudentsAddDepartmentBinding:
    def test_head_add_binds_student_to_department_and_lists_them(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code = f"ME{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "ميكانيكا", "Mechanical"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        cur.execute(
            """
            INSERT INTO programs (department_id, code, name_ar, name_en, phase, is_active)
            VALUES (?, 'PROG_MAJOR', 'بكالوريوس ميكانيكا', 'ME BS', 'major', 1)
            """,
            (dept_id,),
        )
        prog_id = cur.execute(
            "SELECT id FROM programs WHERE department_id = ? AND code = 'PROG_MAJOR'",
            (dept_id,),
        ).fetchone()[0]
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_add_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, dept_id),
        )
        db_conn.commit()

        sid = f"ADD{uid}"
        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            resp = c.post(
                "/students/add",
                json={"student_id": sid, "student_name": "احمد ميكانيكا"},
            )
            assert resp.status_code == 200, resp.get_data(as_text=True)
            body = resp.get_json() or {}
            assert body.get("status") == "ok"
            assert body.get("department_id") == int(dept_id)

            lst = c.get("/students/list")
            assert lst.status_code == 200
            ids = {x.get("student_id") for x in (lst.get_json() or [])}
            assert sid in ids

        row = cur.execute(
            "SELECT department_id, current_program_id FROM students WHERE student_id = ?",
            (sid,),
        ).fetchone()
        assert int(row[0]) == int(dept_id)
        assert int(row[1]) == int(prog_id)

    def test_admin_main_without_scope_does_not_bind_on_add(self, app, db_conn, auth_client):
        uid = uuid.uuid4().hex[:8]
        sid = f"ADMADD{uid}"
        resp = auth_client.post(
            "/students/add",
            json={"student_id": sid, "student_name": "طالب بلا نطاق"},
        )
        assert resp.status_code == 200
        body = resp.get_json() or {}
        assert body.get("status") == "ok"
        assert "department_id" not in body

        row = db_conn.execute(
            "SELECT department_id FROM students WHERE student_id = ?",
            (sid,),
        ).fetchone()
        assert row[0] is None
