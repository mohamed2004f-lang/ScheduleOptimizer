"""اختبارات استيراد المقررات من Excel وربطها بقسم المنفّذ."""

from __future__ import annotations

import io
import uuid

import pandas as pd


def _courses_excel_bytes(rows: list[dict]) -> io.BytesIO:
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    buf.seek(0)
    return buf


class TestCoursesImportExcelDepartmentBinding:
    def test_head_import_binds_courses_to_department_and_lists_them(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code = f"CM{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "مدني", "Civil"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        other_code = f"OM{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (other_code, "آخر", "Other"),
        )
        other_dept = cur.execute("SELECT id FROM departments WHERE code = ?", (other_code,)).fetchone()[0]
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (f"Other-{uid}", "OTH101", 3, other_dept),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_crs_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, dept_id),
        )
        db_conn.commit()

        c1 = f"Statics-{uid}"
        c2 = f"Concrete-{uid}"
        xls = _courses_excel_bytes(
            [
                {"course_name": c1, "course_code": "CE201", "units": 3},
                {"course_name": c2, "course_code": "CE202", "units": 3},
            ]
        )

        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            imp = c.post(
                "/courses/import/excel",
                data={"file": (xls, "courses.xlsx")},
                content_type="multipart/form-data",
            )
            assert imp.status_code == 200, imp.get_data(as_text=True)
            body = imp.get_json() or {}
            assert body.get("status") == "ok"
            assert body.get("imported") == 2
            assert body.get("department_id") == int(dept_id)
            assert body.get("department_bound") == 2

            lst = c.get("/courses/list")
            assert lst.status_code == 200
            names = {x.get("course_name") for x in (lst.get_json() or [])}
            assert c1 in names
            assert c2 in names
            assert f"Other-{uid}" not in names

        row = cur.execute(
            "SELECT owning_department_id FROM courses WHERE course_name = ?",
            (c1,),
        ).fetchone()
        assert int(row[0]) == int(dept_id)

    def test_staff_with_department_scope_filters_students(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code = f"SR{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "مدني", "Civil"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        s1 = f"ST{uid}1"
        s2 = f"ST{uid}2"
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (s1, "طالب 1", dept_id),
        )
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status) VALUES (?, ?, 'active')",
            (s2, "طالب 2"),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        staff_user = f"registrar_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'staff')",
            (staff_user, pw),
        )
        db_conn.commit()

        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": staff_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            all_lst = c.get("/students/list")
            assert all_lst.status_code == 200
            all_ids = {x.get("student_id") for x in (all_lst.get_json() or [])}
            assert s1 in all_ids
            assert s2 in all_ids

            sc = c.post(
                "/auth/admin_department_scope",
                json={"department_id": int(dept_id)},
            )
            assert sc.status_code == 200
            scoped = c.get("/students/list")
            assert scoped.status_code == 200
            scoped_ids = {x.get("student_id") for x in (scoped.get_json() or [])}
            assert s1 in scoped_ids
            assert s2 not in scoped_ids
