"""تقرير التسجيل (قائمة الطلبة) + حضور من التسجيل الفعلي بدون اشتراط الجدول."""
from __future__ import annotations

import uuid


def _set_current_term(cur, semester: str = "خريف 44-45") -> str:
    parts = semester.rsplit(" ", 1)
    tname = parts[0] if len(parts) == 2 else semester
    tyear = parts[1] if len(parts) == 2 else ""
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', ?)",
        (tname,),
    )
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', ?)",
        (tyear,),
    )
    return semester


class TestRegistrationRosterAndAttendance:
    def test_course_registration_roster_lists_students(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"RR{uid}"[:12].upper(), "مدني", "Civil"),
        )
        dept_id = cur.execute(
            "SELECT id FROM departments WHERE code = ?", (f"RR{uid}"[:12].upper(),)
        ).fetchone()[0]
        course = f"Roster-{uid}"
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
            (course, "RR101", dept_id),
        )
        s1, s2 = f"RS{uid}1", f"RS{uid}2"
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id, enrollment_status) VALUES (?, ?, ?, 'active')",
            (s1, "أحمد", dept_id),
        )
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id, enrollment_status) VALUES (?, ?, ?, 'active')",
            (s2, "سارة", dept_id),
        )
        cur.execute("INSERT INTO registrations (student_id, course_name) VALUES (?, ?)", (s1, course))
        cur.execute("INSERT INTO registrations (student_id, course_name) VALUES (?, ?)", (s2, course))
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_rr_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, dept_id),
        )
        db_conn.commit()

        with app.test_client() as c:
            assert c.post(
                "/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}
            ).status_code == 200
            r = c.get(
                "/students/course_registration_counts/roster",
                query_string={"course_name": course},
            )
            assert r.status_code == 200, r.get_data(as_text=True)
            body = r.get_json() or {}
            assert body.get("student_count") == 2
            names = {x.get("student_name") for x in body.get("students") or []}
            assert "أحمد" in names and "سارة" in names

    def test_attendance_courses_from_registration_without_schedule(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"AT{uid}"[:12].upper(), "مدني", "Civil"),
        )
        dept_id = cur.execute(
            "SELECT id FROM departments WHERE code = ?", (f"AT{uid}"[:12].upper(),)
        ).fetchone()[0]
        course = f"AttReg-{uid}"
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
            (course, "AT101", dept_id),
        )
        sid = f"AS{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id, enrollment_status) VALUES (?, ?, ?, 'active')",
            (sid, "طالب", dept_id),
        )
        cur.execute("INSERT INTO registrations (student_id, course_name) VALUES (?, ?)", (sid, course))
        _set_current_term(cur)
        # لا صف في schedule — يجب أن يظهر المقرر من التسجيل الفعلي
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_att_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, dept_id),
        )
        db_conn.commit()

        with app.test_client() as c:
            assert c.post(
                "/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}
            ).status_code == 200
            r = c.get("/students/attendance_allowed_courses")
            assert r.status_code == 200, r.get_data(as_text=True)
            body = r.get_json() or {}
            names = {x.get("course_name") for x in body.get("courses") or []}
            assert course in names
            row = next(x for x in body["courses"] if x.get("course_name") == course)
            assert row.get("registration_only") is True
            assert body.get("source") == "registrations"

    def test_hod_attendance_includes_null_general_shared_and_schedule_dept(self, app, db_conn):
        """رئيس تخصص يرى مقررات طلبته: NULL owning + GENERAL + مشترك + جدول القسم رغم ملكية خاطئة."""
        from backend.core.college_shared_catalog import save_catalog_entry

        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) "
            "VALUES ('GENERAL', 'اتجاه عام', 'General', 1)"
        )
        gen_id = int(cur.execute("SELECT id FROM departments WHERE code='GENERAL'").fetchone()[0])
        home_code = f"HM{uid}"[:12].upper()
        other_code = f"OT{uid}"[:12].upper()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (home_code, "ميكانيكا", "Mech"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (other_code, "كهرباء", "Elec"),
        )
        home_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (home_code,)).fetchone()[0])
        other_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (other_code,)).fetchone()[0])

        c_null = f"NullOwn-{uid}"
        c_gen = f"GenOwn-{uid}"
        c_shared = f"SharedAtt-{uid}"
        c_sched = f"SchedOwn-{uid}"
        # ملكية فارغة (مثل تقنية ورش دون owning)
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, NULL)",
            (c_null, f"N{uid[:4]}",),
        )
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
            (c_gen, f"G{uid[:4]}", gen_id),
        )
        # ملكية قسم آخر لكن صف جدول للقسم المنزل
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
            (c_sched, f"S{uid[:4]}", other_id),
        )
        save_catalog_entry(
            db_conn,
            {
                "catalog_key": f"att_sh_{uid}",
                "share_type": "unified",
                "canonical_course_name": c_shared,
                "canonical_course_code": f"SH{uid[:3]}",
                "units": 3,
                "requirement_scope": "pre_track",
            },
        )

        sid = f"ST{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, department_id, enrollment_status) "
            "VALUES (?, ?, ?, 'active')",
            (sid, "طالب قسم", home_id),
        )
        for cn in (c_null, c_gen, c_shared, c_sched):
            cur.execute(
                "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
                (sid, cn),
            )
        sem = _set_current_term(cur)
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, semester, instructor, department_id)
            VALUES (?, 'الأحد', '08:00', ?, 'أستاذ', ?)
            """,
            (c_sched, sem, home_id),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_att_scope_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) "
            "VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, home_id),
        )
        db_conn.commit()

        with app.test_client() as c:
            assert c.post(
                "/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}
            ).status_code == 200
            r = c.get("/students/attendance_allowed_courses")
            assert r.status_code == 200, r.get_data(as_text=True)
            names = {x.get("course_name") for x in (r.get_json() or {}).get("courses") or []}
            assert c_null in names
            assert c_gen in names
            assert c_shared in names
            assert c_sched in names
