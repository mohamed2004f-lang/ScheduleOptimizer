"""Sprint B: ربط التسجيل بـ program_courses والتحقق الأساسي."""


class TestRegistrationProgramCoursePolicy:
    def test_save_registrations_sets_program_course_id(self, auth_client, db_conn):
        cur = db_conn.cursor()
        # برنامج عام للطالب S001
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES ('RGP1', 'قسم', 'Dept', 1)"
        )
        dep_id = cur.execute("SELECT id FROM departments WHERE code = 'RGP1'").fetchone()[0]
        cur.execute(
            """
            INSERT INTO programs (department_id, code, name_ar, phase, is_active)
            VALUES (?, 'GEN', 'برنامج عام', 'general', 1)
            """,
            (dep_id,),
        )
        prog_id = cur.execute("SELECT id FROM programs WHERE code = 'GEN' LIMIT 1").fetchone()[0]

        # ربط المقرر رياضيات 1 بخطة البرنامج عبر course_master + program_courses
        cur.execute(
            "INSERT INTO course_master (title_ar, default_units, grading_mode, assessment_type) VALUES ('رياضيات 1', 3, 'partial_final', 'theoretical')"
        )
        cm_id = cur.execute("SELECT id FROM course_master WHERE title_ar = 'رياضيات 1' LIMIT 1").fetchone()[0]
        cur.execute(
            "UPDATE courses SET course_master_id = ? WHERE course_name = 'رياضيات 1'",
            (cm_id,),
        )
        cur.execute(
            """
            INSERT INTO program_courses (program_id, course_master_id, course_code, course_name_override, is_required, is_active)
            VALUES (?, ?, 'MATH101', 'رياضيات 1', 1, 1)
            """,
            (prog_id, cm_id),
        )
        pc_id = cur.execute(
            "SELECT id FROM program_courses WHERE program_id = ? AND course_code = 'MATH101' LIMIT 1",
            (prog_id,),
        ).fetchone()[0]

        cur.execute(
            "UPDATE students SET current_program_id = ?, admission_program_id = ?, enrollment_status = 'active' WHERE student_id = 'S001'",
            (prog_id, prog_id),
        )
        db_conn.commit()

        r = auth_client.post(
            "/students/save_registrations",
            json={
                "student_id": "S001",
                "courses": ["رياضيات 1"],
                "override_reason": "test",
            },
            headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        assert r.status_code == 200
        row = db_conn.execute(
            "SELECT program_course_id FROM registrations WHERE student_id = 'S001' AND course_name = 'رياضيات 1' LIMIT 1"
        ).fetchone()
        assert row is not None
        assert int(row[0] or 0) == int(pc_id)

