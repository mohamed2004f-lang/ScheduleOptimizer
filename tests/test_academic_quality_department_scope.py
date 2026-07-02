"""نطاق القسم في شاشات الجودة — عميد / وكيل / مسجل."""

from __future__ import annotations

import uuid

from backend.services.survey_completion import resolve_completion_department_id


class TestAcademicQualityDepartmentScope:
    def test_dean_session_scope_filters_institutional_inputs(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        sem = f"Q-{uid}"
        cur = db_conn.cursor()
        code = f"QD{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "جودة", "Quality"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        cur.execute(
            """
            INSERT INTO quality_institutional_inputs
                (semester, department_id, faculty_qualifications_percent, infrastructure_rating, notes)
            VALUES (?, NULL, 50, 3, 'college')
            """,
            (sem,),
        )
        cur.execute(
            """
            INSERT INTO quality_institutional_inputs
                (semester, department_id, faculty_qualifications_percent, infrastructure_rating, notes)
            VALUES (?, ?, 80, 4, 'dept')
            """,
            (sem, int(dept_id)),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        dean_user = f"dean_q_{uid}"
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

            college = c.get(f"/academic_quality/api/institutional_inputs?semester={sem}")
            assert college.status_code == 200
            assert college.get_json().get("inputs", {}).get("faculty_qualifications_percent") == 50

            assert c.post(
                "/auth/admin_department_scope",
                json={"department_id": int(dept_id)},
            ).status_code == 200

            scoped = c.get(f"/academic_quality/api/institutional_inputs?semester={sem}")
            assert scoped.status_code == 200
            assert scoped.get_json().get("inputs", {}).get("faculty_qualifications_percent") == 80

    def test_staff_in_completion_admin_roles(self, db_conn):
        uid = uuid.uuid4().hex[:8]
        code = f"QS{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "مسجل", "Registrar"),
        )
        dept_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        db_conn.commit()

        dep, can_pick = resolve_completion_department_id(
            db_conn,
            role="staff",
            username="registrar",
            session_scope_id=int(dept_id),
        )
        assert dep == int(dept_id)
        assert can_pick is True
