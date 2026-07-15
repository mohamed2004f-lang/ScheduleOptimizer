"""اختبارات نطاق القسم في الاستيراد والتصدير."""

from __future__ import annotations

import io
import json
import uuid

import pandas as pd
import pytest


def _xls_bytes(rows: list[dict]) -> io.BytesIO:
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    buf.seek(0)
    return buf


class TestDepartmentScopeImportExport:
    def test_grades_semester_import_rejects_other_department_student(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"GC{uid}"[:12].upper(), "مدني", "Civil"),
        )
        dept_id = cur.execute(
            "SELECT id FROM departments WHERE code = ?", (f"GC{uid}"[:12].upper(),)
        ).fetchone()[0]
        other_code = f"GO{uid}"[:12].upper()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (other_code, "ميكانيك", "Mech"),
        )
        other_dept = cur.execute("SELECT id FROM departments WHERE code = ?", (other_code,)).fetchone()[0]
        civil_course = f"CivG-{uid}"
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (civil_course, "CE401", 3, dept_id),
        )
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (f"MechG-{uid}", "ME401", 3, other_dept),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_gr_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, dept_id),
        )
        s_civil = f"ST{uid}1"
        s_mech = f"ST{uid}2"
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
            (s_civil, "طالب مدني", dept_id),
        )
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
            (s_mech, "طالب ميكانيك", other_dept),
        )
        db_conn.commit()

        # semester import matrix: row0 headers, row1 units, row2+ students
        df = pd.DataFrame(
            [
                ["الاسم", "الرقم", civil_course, f"MechG-{uid}"],
                ["", "", 3, 3],
                ["طالب مدني", s_civil, 80, 70],
                ["طالب ميكانيك", s_mech, 75, 65],
            ]
        )
        buf = io.BytesIO()
        df.to_excel(buf, index=False, header=False)
        buf.seek(0)

        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            bad = c.post(
                "/grades/import/semester",
                data={
                    "file": (buf, "grades.xlsx"),
                    "semester": "خريف",
                    "year": "44-45",
                    "preview": "1",
                },
                content_type="multipart/form-data",
            )
            assert bad.status_code == 400

            buf2 = io.BytesIO()
            pd.DataFrame(
                [
                    ["الاسم", "الرقم", civil_course],
                    ["", "", 3],
                    ["طالب مدني", s_civil, 80],
                ]
            ).to_excel(buf2, index=False, header=False)
            buf2.seek(0)
            ok = c.post(
                "/grades/import/semester",
                data={
                    "file": (buf2, "grades.xlsx"),
                    "semester": "خريف",
                    "year": "44-45",
                    "preview": "1",
                },
                content_type="multipart/form-data",
            )
            assert ok.status_code == 200, ok.get_data(as_text=True)
            body = ok.get_json() or {}
            assert body.get("students") == 1

    def test_import_registrations_skips_out_of_scope(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"RC{uid}"[:12].upper(), "مدني", "Civil"),
        )
        dept_id = cur.execute(
            "SELECT id FROM departments WHERE code = ?", (f"RC{uid}"[:12].upper(),)
        ).fetchone()[0]
        other_code = f"RO{uid}"[:12].upper()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (other_code, "ميكانيك", "Mech"),
        )
        other_dept = cur.execute("SELECT id FROM departments WHERE code = ?", (other_code,)).fetchone()[0]
        civil_course = f"CivR-{uid}"
        mech_course = f"MechR-{uid}"
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (civil_course, "CE501", 3, dept_id),
        )
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (mech_course, "ME501", 3, other_dept),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_reg_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, dept_id),
        )
        s_ok = f"ST{uid}1"
        s_bad = f"ST{uid}2"
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
            (s_ok, "طالب 1", dept_id),
        )
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
            (s_bad, "طالب 2", other_dept),
        )
        db_conn.commit()

        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            r = c.post(
                "/students/import_registrations",
                json={
                    "items": [
                        {"student_id": s_ok, "registrations": [civil_course]},
                        {"student_id": s_bad, "registrations": [mech_course]},
                        {"student_id": s_ok, "registrations": [mech_course]},
                    ]
                },
            )
            assert r.status_code == 200
            body = r.get_json() or {}
            assert body.get("imported") == 1
            assert body.get("skipped") == 2

    def test_course_registration_counts_scoped(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"CC{uid}"[:12].upper(), "مدني", "Civil"),
        )
        dept_id = cur.execute(
            "SELECT id FROM departments WHERE code = ?", (f"CC{uid}"[:12].upper(),)
        ).fetchone()[0]
        other_code = f"CO{uid}"[:12].upper()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (other_code, "ميكانيك", "Mech"),
        )
        other_dept = cur.execute("SELECT id FROM departments WHERE code = ?", (other_code,)).fetchone()[0]
        civil_course = f"CivC-{uid}"
        mech_course = f"MechC-{uid}"
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (civil_course, "CE601", 3, dept_id),
        )
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (mech_course, "ME601", 3, other_dept),
        )
        s1 = f"ST{uid}1"
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id, enrollment_status) VALUES (?, ?, ?, 'active')",
            (s1, "طالب", dept_id),
        )
        cur.execute(
            "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
            (s1, civil_course),
        )
        cur.execute(
            "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
            (s1, mech_course),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_cnt_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, dept_id),
        )
        db_conn.commit()

        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            r = c.get("/students/course_registration_counts")
            assert r.status_code == 200
            items = (r.get_json() or {}).get("items") or []
            names = {x.get("course_name") for x in items}
            assert civil_course in names
            assert mech_course not in names

    def test_schedule_import_excel_scoped(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"SC{uid}"[:12].upper(), "مدني", "Civil"),
        )
        dept_id = cur.execute(
            "SELECT id FROM departments WHERE code = ?", (f"SC{uid}"[:12].upper(),)
        ).fetchone()[0]
        other_code = f"SO{uid}"[:12].upper()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (other_code, "ميكانيك", "Mech"),
        )
        other_dept = cur.execute("SELECT id FROM departments WHERE code = ?", (other_code,)).fetchone()[0]
        civil_course = f"CivS-{uid}"
        mech_course = f"MechS-{uid}"
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (civil_course, "CE701", 3, dept_id),
        )
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (mech_course, "ME701", 3, other_dept),
        )
        cur.execute(
            "INSERT OR REPLACE INTO app_settings (key, value_json) VALUES ('current_term', ?)",
            (json.dumps({"term_name": "خريف", "term_year": "44-45"}),),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_sch_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, dept_id),
        )
        db_conn.commit()

        xls = _xls_bytes(
            [
                {
                    "course_name": civil_course,
                    "day": "الأحد",
                    "time": "08:00-10:00",
                    "room": "101",
                    "instructor": "د. أ",
                },
                {
                    "course_name": mech_course,
                    "day": "الاثنين",
                    "time": "10:00-12:00",
                    "room": "102",
                    "instructor": "د. ب",
                },
            ]
        )

        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            imp = c.post(
                "/schedule/import/excel",
                data={"file": (xls, "schedule.xlsx")},
                content_type="multipart/form-data",
            )
            assert imp.status_code == 200, imp.get_data(as_text=True)
            body = imp.get_json() or {}
            assert body.get("imported") == 1
            assert body.get("skipped") == 1

        rows = cur.execute(
            "SELECT course_name FROM schedule WHERE course_name IN (?, ?)",
            (civil_course, mech_course),
        ).fetchall()
        names = {r[0] for r in rows}
        assert civil_course in names
        assert mech_course not in names

    def test_backfill_courses_owning_department(self, db_conn):
        from backend.core.department_scope_policy import backfill_courses_owning_department_from_schedule

        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"BF{uid}"[:12].upper(), "مدني", "Civil"),
        )
        dept_id = int(
            cur.execute(
                "SELECT id FROM departments WHERE code = ?", (f"BF{uid}"[:12].upper(),)
            ).fetchone()[0]
        )
        cname = f"Orphan-{uid}"
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, NULL)",
            (cname, "OR101", 3),
        )
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor, semester, department_id)
            VALUES (?, 'الأحد', '08:00-10:00', '1', 'د', 'خريف 44-45', ?)
            """,
            (cname, dept_id),
        )
        db_conn.commit()
        n = backfill_courses_owning_department_from_schedule(db_conn, department_id=dept_id)
        db_conn.commit()
        assert n >= 1
        row = cur.execute(
            "SELECT owning_department_id FROM courses WHERE course_name = ?", (cname,)
        ).fetchone()
        assert int(row[0]) == dept_id

    def test_college_general_courses_visible_to_all_departments(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            ("GENERAL", "الاتجاه العام", "General",),
        )
        gen_dept = cur.execute("SELECT id FROM departments WHERE code = 'GENERAL'").fetchone()[0]
        civil_code = f"CV{uid}"[:12].upper()
        mech_code = f"MC{uid}"[:12].upper()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (civil_code, "مدني", "Civil"),
        )
        civil_dept = cur.execute("SELECT id FROM departments WHERE code = ?", (civil_code,)).fetchone()[0]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (mech_code, "ميكانيك", "Mech"),
        )
        mech_dept = cur.execute("SELECT id FROM departments WHERE code = ?", (mech_code,)).fetchone()[0]
        civil_course = f"CivOnly-{uid}"
        mech_course = f"MechOnly-{uid}"
        gen_course = f"Gen-{uid}"
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (civil_course, f"CE{uid[:4]}", 3, civil_dept),
        )
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (mech_course, f"ME{uid[:4]}", 3, mech_dept),
        )
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (gen_course, f"GN{uid[:4]}", 3, gen_dept),
        )
        cur.execute(
            "INSERT OR IGNORE INTO programs (code, name_ar, department_id, is_active) VALUES (?, ?, ?, 1)",
            ("PROG_U1", "اتجاه عام", gen_dept),
        )
        prog_id = cur.execute("SELECT id FROM programs WHERE code = 'PROG_U1'").fetchone()[0]
        cur.execute(
            """
            INSERT INTO course_master (title_ar, default_units, assessment_type)
            VALUES (?, ?, 'theoretical')
            """,
            (gen_course, 3),
        )
        cm_id = cur.execute(
            "SELECT id FROM course_master WHERE title_ar = ?", (gen_course,)
        ).fetchone()[0]
        cur.execute(
            """
            INSERT INTO program_courses (program_id, course_master_id, course_code, requirement_scope, is_active)
            VALUES (?, ?, ?, 'college_general', 1)
            """,
            (prog_id, cm_id, f"GN{uid[:4]}"),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_civil = f"head_cg_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_civil, pw, civil_dept),
        )
        db_conn.commit()

        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_civil, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            r = c.get("/courses/list")
            assert r.status_code == 200
            names = {x.get("course_name") for x in (r.get_json() or [])}
            assert civil_course in names
            assert gen_course in names
            assert mech_course not in names

        from backend.core.department_scope_policy import (
            assert_course_in_actor_scope,
            course_in_actor_scope,
        )

        assert course_in_actor_scope(db_conn, gen_course, head_civil)
        assert course_in_actor_scope(db_conn, civil_course, head_civil)
        assert not course_in_actor_scope(db_conn, mech_course, head_civil)
        assert_course_in_actor_scope(db_conn, gen_course, head_civil)

    def test_college_general_import_not_bound_to_importer_department(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            ("GENERAL", "الاتجاه العام", "General",),
        )
        gen_dept = int(cur.execute("SELECT id FROM departments WHERE code = 'GENERAL'").fetchone()[0])
        civil_code = f"IC{uid}"[:12].upper()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (civil_code, "مدني", "Civil"),
        )
        civil_dept = int(cur.execute("SELECT id FROM departments WHERE code = ?", (civil_code,)).fetchone()[0])
        gen_course = f"GenImp-{uid}"
        gen_code = f"GI{uid[:4]}"
        cur.execute(
            "INSERT OR IGNORE INTO programs (code, name_ar, department_id, is_active) VALUES (?, ?, ?, 1)",
            ("PROG_U1", "اتجاه عام", gen_dept),
        )
        prog_id = cur.execute("SELECT id FROM programs WHERE code = 'PROG_U1'").fetchone()[0]
        cur.execute(
            """
            INSERT INTO course_master (title_ar, default_units, assessment_type)
            VALUES (?, ?, 'theoretical')
            """,
            (gen_course, 3),
        )
        cm_id = cur.execute("SELECT id FROM course_master WHERE title_ar = ?", (gen_course,)).fetchone()[0]
        cur.execute(
            """
            INSERT INTO program_courses (program_id, course_master_id, course_code, requirement_scope, is_active)
            VALUES (?, ?, ?, 'college_general', 1)
            """,
            (prog_id, cm_id, gen_code),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_civil = f"head_imp_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_civil, pw, civil_dept),
        )
        db_conn.commit()

        xls = _xls_bytes([{"course_name": gen_course, "course_code": gen_code, "units": 3}])
        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_civil, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            imp = c.post(
                "/courses/import/excel",
                data={"file": (xls, "courses.xlsx")},
                content_type="multipart/form-data",
            )
            assert imp.status_code == 200, imp.get_data(as_text=True)

        row = cur.execute(
            "SELECT owning_department_id FROM courses WHERE course_name = ?", (gen_course,)
        ).fetchone()
        assert row is not None
        assert int(row[0]) == gen_dept
