"""اختبارات الإدخال اليدوي للجدول الدراسي مع ربط القسم."""

from __future__ import annotations

import uuid


class TestScheduleManualDepartmentBinding:
    def test_head_manual_add_binds_department_and_lists_row(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code = f"SH{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "مدني", "Civil"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_sched_add_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, dept_id),
        )
        db_conn.commit()

        course = f"Survey-{uid}"
        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            add = c.post(
                "/schedule/add_row",
                json={
                    "course_name": course,
                    "day": "الأحد",
                    "time": "08:00-09:00",
                    "room": "R1",
                    "instructor": "Dr. X",
                    "semester": "خريف 25-26",
                },
            )
            assert add.status_code == 200, add.get_data(as_text=True)

            lst = c.get("/schedule/rows")
            assert lst.status_code == 200
            rows = lst.get_json() or []
            names = {x.get("course_name") for x in rows}
            assert course in names

        row = cur.execute(
            "SELECT department_id FROM schedule WHERE course_name = ?",
            (course,),
        ).fetchone()
        assert row is not None
        assert int(row[0]) == int(dept_id)
