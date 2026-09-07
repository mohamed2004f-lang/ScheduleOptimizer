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
