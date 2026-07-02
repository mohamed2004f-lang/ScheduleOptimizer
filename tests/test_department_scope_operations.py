"""توحيد نطاق القسم: امتحانات، حضور، تنفيذ مقررات."""

from __future__ import annotations

import uuid

from backend.services.course_delivery import BASELINE_PENDING, ensure_course_delivery_schema


def _ensure_exams_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type TEXT NOT NULL,
            exam_id INTEGER,
            course_name TEXT NOT NULL,
            exam_date TEXT,
            exam_time TEXT,
            room TEXT DEFAULT '',
            instructor TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


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


class TestExamsDepartmentScope:
    def test_dean_session_scope_filters_exam_rows(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        _ensure_exams_table(cur)
        code_a = f"EA{uid}".upper()[:12]
        code_b = f"EB{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code_a, "امتحان أ", "Exam A"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code_b, "امتحان ب", "Exam B"),
        )
        dept_a = cur.execute("SELECT id FROM departments WHERE code = ?", (code_a,)).fetchone()[0]
        dept_b = cur.execute("SELECT id FROM departments WHERE code = ?", (code_b,)).fetchone()[0]
        c_a = f"CourseA-{uid}"
        c_b = f"CourseB-{uid}"
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
            (c_a, "EA101", int(dept_a)),
        )
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
            (c_b, "EB101", int(dept_b)),
        )
        cur.execute(
            "INSERT INTO exams (course_name, exam_type, exam_date, exam_time) VALUES (?, 'midterm', '2026-01-10', '09:00')",
            (c_a,),
        )
        cur.execute(
            "INSERT INTO exams (course_name, exam_type, exam_date, exam_time) VALUES (?, 'midterm', '2026-01-11', '09:00')",
            (c_b,),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        dean_user = f"dean_ex_{uid}"
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
            all_rows = c.get("/exams/midterm/rows")
            assert all_rows.status_code == 200
            all_names = {x.get("course_name") for x in (all_rows.get_json() or [])}
            assert c_a in all_names
            assert c_b in all_names

            assert c.post(
                "/auth/admin_department_scope",
                json={"department_id": int(dept_a)},
            ).status_code == 200
            scoped = c.get("/exams/midterm/rows")
            assert scoped.status_code == 200
            scoped_names = {x.get("course_name") for x in (scoped.get_json() or [])}
            assert c_a in scoped_names
            assert c_b not in scoped_names


class TestAttendanceDepartmentScope:
    def test_dean_can_list_scoped_attendance_courses(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        code = f"AT{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "حضور", "Attend"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        other_code = f"AO{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (other_code, "آخر", "Other"),
        )
        other_dept = cur.execute("SELECT id FROM departments WHERE code = ?", (other_code,)).fetchone()[0]
        c1 = f"AttC1-{uid}"
        c2 = f"AttC2-{uid}"
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
            (c1, "AT101", int(dept_id)),
        )
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
            (c2, "AT102", int(other_dept)),
        )
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (f"ST{uid}1", "طالب 1", int(dept_id)),
        )
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (f"ST{uid}2", "طالب 2", int(other_dept)),
        )
        cur.execute(
            "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
            (f"ST{uid}1", c1),
        )
        cur.execute(
            "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
            (f"ST{uid}2", c2),
        )
        sem = _set_current_term(cur)
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, semester, instructor, department_id)
            VALUES (?, 'الأحد', '08:00', ?, 'أستاذ', ?)
            """,
            (c1, sem, int(dept_id)),
        )
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, semester, instructor, department_id)
            VALUES (?, 'الأحد', '08:00', ?, 'أستاذ', ?)
            """,
            (c2, sem, int(other_dept)),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        dean_user = f"dean_att_{uid}"
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
            before = c.get("/students/attendance_allowed_courses")
            assert before.status_code == 200, before.get_data(as_text=True)
            before_names = {x.get("course_name") for x in (before.get_json() or {}).get("courses", [])}
            assert c1 in before_names or c2 in before_names

            assert c.post(
                "/auth/admin_department_scope",
                json={"department_id": int(dept_id)},
            ).status_code == 200
            after = c.get("/students/attendance_allowed_courses")
            assert after.status_code == 200
            after_names = {x.get("course_name") for x in (after.get_json() or {}).get("courses", [])}
            assert c1 in after_names
            assert c2 not in after_names


class TestCourseDeliveryHodScope:
    def test_hod_pending_uses_home_department_not_college_wide(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        code = f"HD{uid}".upper()[:12]
        other_code = f"HO{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "قسم رئيس", "HOD Dept"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (other_code, "قسم آخر", "Other Dept"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        other_dept = cur.execute("SELECT id FROM departments WHERE code = ?", (other_code,)).fetchone()[0]
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_cd_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, int(dept_id)),
        )
        ensure_course_delivery_schema(db_conn)
        sem = _set_current_term(cur)
        cur.execute(
            """
            INSERT INTO course_syllabus_baselines (course_name, version, status, semester_label)
            VALUES (?, 1, ?, ?)
            """,
            (f"Mine-{uid}", BASELINE_PENDING, sem),
        )
        cur.execute(
            """
            INSERT INTO course_syllabus_baselines (course_name, version, status, semester_label)
            VALUES (?, 1, ?, ?)
            """,
            (f"Other-{uid}", BASELINE_PENDING, sem),
        )
        cur.execute(
            """
            INSERT INTO teaching_groups (group_code, course_name, semester, department_id, instructor_id, is_active)
            VALUES (?, ?, ?, ?, 1, 1)
            """,
            (f"TG{uid}", f"Mine-{uid}", sem, int(dept_id)),
        )
        db_conn.commit()

        with app.test_client() as c:
            assert c.post(
                "/auth/login",
                json={"username": head_user, "password": "TestP@ssw0rd!"},
            ).status_code == 200
            r = c.get("/course_delivery/hod/pending")
            assert r.status_code == 200, r.get_data(as_text=True)
            body = r.get_json() or {}
            assert body.get("summary", {}).get("department_id") == int(dept_id)
            names = {(b.get("course_name") or "") for b in body.get("pending_baselines") or []}
            assert f"Mine-{uid}" in names
            assert f"Other-{uid}" not in names
