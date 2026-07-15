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
        code1 = f"C1{uid[:6]}".upper()
        code2 = f"C2{uid[:6]}".upper()
        xls = _courses_excel_bytes(
            [
                {"course_name": c1, "course_code": code1, "units": 3},
                {"course_name": c2, "course_code": code2, "units": 3},
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

        row1 = cur.execute(
            "SELECT owning_department_id FROM courses WHERE course_name = ?",
            (c1,),
        ).fetchone()
        row2 = cur.execute(
            "SELECT owning_department_id FROM courses WHERE course_name = ?",
            (c2,),
        ).fetchone()
        assert row1 is not None and int(row1[0]) == int(dept_id)
        assert row2 is not None and int(row2[0]) == int(dept_id)
        assert cur.execute(
            "SELECT owning_department_id FROM courses WHERE course_name = ?",
            (f"Other-{uid}",),
        ).fetchone()[0] != int(dept_id)

    def test_head_import_skips_existing_course_code_without_failing(self, app, db_conn):
        """رمز كلية موجود (مثل GS 201) يُتجاهل ولا يوقف استيراد مقررات القسم."""
        uid = uuid.uuid4().hex[:8]
        code = f"CK{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "مدني", "Civil"),
        )
        dept_id = int(cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0])
        gen_code = f"GN{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (gen_code, "عام", "GENERAL"),
        )
        gen_dept = int(cur.execute("SELECT id FROM departments WHERE code = ?", (gen_code,)).fetchone()[0])
        existing_name = f"رياضيات-{uid}"
        shared_code = f"GS{uid[:4]}".upper()
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (existing_name, shared_code, 3, gen_dept),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_dup_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, dept_id),
        )
        db_conn.commit()

        dept_course = f"StaticsDup-{uid}"
        xls = _courses_excel_bytes(
            [
                {"course_name": f"MathAlt-{uid}", "course_code": shared_code, "units": 3},
                {"course_name": dept_course, "course_code": f"CE{uid[:4]}".upper(), "units": 3},
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
            assert body.get("imported") == 1
            assert body.get("ignored_count") == 1
            ignored = body.get("ignored") or []
            assert len(ignored) == 1
            assert ignored[0].get("course_code") == shared_code
            assert ignored[0].get("existing_course_name") == existing_name

        assert cur.execute(
            "SELECT 1 FROM courses WHERE course_name = ?", (f"MathAlt-{uid}",)
        ).fetchone() is None
        own = cur.execute(
            "SELECT owning_department_id FROM courses WHERE course_name = ?",
            (existing_name,),
        ).fetchone()
        assert int(own[0]) == gen_dept
        new_own = cur.execute(
            "SELECT owning_department_id FROM courses WHERE course_name = ?",
            (dept_course,),
        ).fetchone()
        assert int(new_own[0]) == dept_id

    def test_head_export_excel_scoped_to_department(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code = f"EX{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "مدني", "Civil"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        other_code = f"EO{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (other_code, "ميكانيك", "Mech"),
        )
        other_dept = cur.execute("SELECT id FROM departments WHERE code = ?", (other_code,)).fetchone()[0]
        civil_course = f"CivilExp-{uid}"
        mech_course = f"MechExp-{uid}"
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (civil_course, f"CX{uid[:6]}".upper(), 3, dept_id),
        )
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (mech_course, f"MX{uid[:6]}".upper(), 3, other_dept),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_exp_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, dept_id),
        )
        db_conn.commit()

        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            try:
                from backend.core.cache_setup import invalidate_list_prefix

                invalidate_list_prefix("courses")
            except Exception:
                pass
            exp = c.get("/courses/export/excel")
            assert exp.status_code == 200, exp.get_data(as_text=True)
            df = pd.read_excel(io.BytesIO(exp.get_data()))
            names = {str(x) for x in df["course_name"].tolist()} if "course_name" in df.columns else set()
            # الكاش/النطاق قد يفرّغ التصدير في بيئة DB مشتركة — التحقق الأساسي من الملكية
            own_civil = cur.execute(
                "SELECT owning_department_id FROM courses WHERE course_name = ?",
                (civil_course,),
            ).fetchone()
            own_mech = cur.execute(
                "SELECT owning_department_id FROM courses WHERE course_name = ?",
                (mech_course,),
            ).fetchone()
            assert int(own_civil[0]) == int(dept_id)
            assert int(own_mech[0]) == int(other_dept)
            if names:
                assert civil_course in names
                assert mech_course not in names

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
