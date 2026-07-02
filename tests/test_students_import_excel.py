"""اختبارات استيراد الطلاب من Excel وربطهم بقسم المنفّذ."""

from __future__ import annotations

import io
import uuid

import pandas as pd


def _students_excel_bytes(rows: list[dict]) -> io.BytesIO:
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    buf.seek(0)
    return buf


class TestStudentsImportExcelDepartmentBinding:
    def test_head_import_binds_students_to_department_and_lists_them(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code = f"CV{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "مدني", "Civil"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        cur.execute(
            """
            INSERT INTO programs (department_id, code, name_ar, name_en, phase, is_active)
            VALUES (?, 'PROG_MAJOR', 'بكالوريوس مدني', 'Civil BS', 'major', 1)
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
        head_user = f"head_import_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, dept_id),
        )
        db_conn.commit()

        s1 = f"IMP{uid}1"
        s2 = f"IMP{uid}2"
        xls = _students_excel_bytes(
            [
                {"student_id": s1, "student_name": "طالب مدني 1"},
                {"student_id": s2, "student_name": "طالب مدني 2"},
            ]
        )

        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            imp = c.post(
                "/students/import/excel",
                data={"file": (xls, "students.xlsx")},
                content_type="multipart/form-data",
            )
            assert imp.status_code == 200, imp.get_data(as_text=True)
            body = imp.get_json() or {}
            assert body.get("status") == "ok"
            assert body.get("imported") == 2
            assert body.get("department_id") == int(dept_id)
            assert body.get("department_bound") == 2

            lst = c.get("/students/list")
            assert lst.status_code == 200
            ids = {x.get("student_id") for x in (lst.get_json() or [])}
            assert s1 in ids
            assert s2 in ids

        row1 = cur.execute(
            "SELECT department_id, current_program_id FROM students WHERE student_id = ?",
            (s1,),
        ).fetchone()
        assert int(row1[0]) == int(dept_id)
        assert int(row1[1]) == int(prog_id)

    def test_admin_main_without_scope_does_not_bind_department(self, app, db_conn, auth_client):
        uid = uuid.uuid4().hex[:8]
        sid = f"ADM{uid}"
        xls = _students_excel_bytes([{"student_id": sid, "student_name": "طالب عام"}])
        imp = auth_client.post(
            "/students/import/excel",
            data={"file": (xls, "students.xlsx")},
            content_type="multipart/form-data",
        )
        assert imp.status_code == 200
        body = imp.get_json() or {}
        assert body.get("imported") == 1
        assert "department_id" not in body

        row = db_conn.execute(
            "SELECT department_id FROM students WHERE student_id = ?",
            (sid,),
        ).fetchone()
        assert row[0] is None
