"""نقل/تحديد قسم الطالب — المسؤول الرئيسي والعميد والوكيل."""

from __future__ import annotations

import uuid


class TestStudentDepartmentTransfer:
    def test_admin_main_transfers_student_department(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        code_a = f"DA{uid}".upper()[:12]
        code_b = f"DB{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code_a, "قسم أ", "Dept A"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code_b, "قسم ب", "Dept B"),
        )
        dept_a = cur.execute("SELECT id FROM departments WHERE code = ?", (code_a,)).fetchone()[0]
        dept_b = cur.execute("SELECT id FROM departments WHERE code = ?", (code_b,)).fetchone()[0]
        cur.execute(
            "INSERT INTO programs (code, name_ar, department_id, is_active) VALUES ('PROG_MAJOR', 'رئيسي أ', ?, 1)",
            (int(dept_a),),
        )
        cur.execute(
            "INSERT INTO programs (code, name_ar, department_id, is_active) VALUES ('PROG_MAJOR', 'رئيسي ب', ?, 1)",
            (int(dept_b),),
        )
        prog_b = cur.execute(
            "SELECT id FROM programs WHERE department_id = ? AND code = 'PROG_MAJOR'",
            (int(dept_b),),
        ).fetchone()[0]
        sid = f"ST{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (sid, "طالب نقل", int(dept_a)),
        )
        db_conn.commit()

        with app.test_client() as c:
            assert c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            ).status_code == 200
            opts = c.get("/students/department/options")
            assert opts.status_code == 200
            assert len((opts.get_json() or {}).get("items") or []) >= 2
            tr = c.post(
                "/students/department/transfer",
                json={"student_id": sid, "department_id": int(dept_b)},
            )
            assert tr.status_code == 200, tr.get_data(as_text=True)
            body = tr.get_json() or {}
            assert body.get("department_id") == int(dept_b)
            assert body.get("program_id") == int(prog_b)

            lst = c.get(f"/students/list?active_only=1&_={uid}")
            assert lst.status_code == 200
            listed = next(
                (x for x in (lst.get_json() or []) if str(x.get("student_id")) == sid),
                None,
            )
            assert listed is not None
            assert listed.get("department_id") == int(dept_b)
            assert (listed.get("department_name") or "").strip() != ""

        row = cur.execute(
            "SELECT department_id, admission_program_id FROM students WHERE student_id = ?",
            (sid,),
        ).fetchone()
        assert int(row[0]) == int(dept_b)
        assert int(row[1]) == int(prog_b)

    def test_dean_can_transfer_in_leadership_mode(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        code = f"DD{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "قسم عميد", "Dean Dept"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        cur.execute(
            "INSERT INTO programs (code, name_ar, department_id, is_active) VALUES ('PROG_MAJOR', 'رئيسي', ?, 1)",
            (int(dept_id),),
        )
        sid = f"SD{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status) VALUES (?, ?, 'active')",
            (sid, "طالب بدون قسم"),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        dean_user = f"dean_st_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'college_dean')",
            (dean_user, pw),
        )
        db_conn.commit()

        with app.test_client() as c:
            assert c.post(
                "/auth/login",
                json={"username": dean_user, "password": "TestP@ssw0rd!"},
            ).status_code == 200
            tr = c.post(
                "/students/department/transfer",
                json={"student_id": sid, "department_id": int(dept_id)},
            )
            assert tr.status_code == 200, tr.get_data(as_text=True)

            lst = c.get(f"/students/list?_={uid}")
            assert lst.status_code == 200
            row = next(
                (x for x in (lst.get_json() or []) if str(x.get("student_id")) == sid),
                None,
            )
            assert row is not None
            assert row.get("department_id") == int(dept_id)
            assert (row.get("department_name") or "").strip() != ""

        row = cur.execute(
            "SELECT department_id FROM students WHERE student_id = ?",
            (sid,),
        ).fetchone()
        assert int(row[0]) == int(dept_id)

    def test_head_of_department_forbidden(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        code = f"DH{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "قسم", "Dept"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        sid = f"SH{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status) VALUES (?, ?, 'active')",
            (sid, "طالب"),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_st_{uid}"
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
            tr = c.post(
                "/students/department/transfer",
                json={"student_id": sid, "department_id": int(dept_id)},
            )
            assert tr.status_code == 403
