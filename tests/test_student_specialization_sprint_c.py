"""Sprint C: إدارة المسار/التخصص وتقارير تجميعية."""
import uuid


class TestStudentSpecializationSprintC:
    def test_update_specialization_updates_student_and_logs(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code = f"TC{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "قسم اختبار مسار", "Track Dept"),
        )
        dep_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        cur.execute(
            """
            INSERT INTO programs (department_id, code, name_ar, phase, is_active)
            VALUES (?, ?, ?, 'major', 1)
            """,
            (dep_id, f"PR{uid}".upper()[:10], "برنامج مسار"),
        )
        prog_id = cur.execute("SELECT id FROM programs WHERE department_id = ? ORDER BY id DESC LIMIT 1", (dep_id,)).fetchone()[0]
        cur.execute(
            "UPDATE students SET department_id = ? WHERE student_id = 'S001'",
            (dep_id,),
        )
        db_conn.commit()

        with app.test_client() as c:
            lr = c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
            assert lr.status_code == 200
            r = c.post(
                "/students/specialization/update",
                json={
                    "student_id": "S001",
                    "current_program_id": prog_id,
                    "track_code": "AI",
                    "specialized_at_term": "خريف 25-26",
                },
            )
            assert r.status_code == 200
            j = r.get_json()
            assert j.get("status") == "ok"
            assert int(j.get("current_program_id") or 0) == int(prog_id)
            assert j.get("track_code") == "AI"

        row = db_conn.execute(
            "SELECT current_program_id, track_code, specialized_at_term FROM students WHERE student_id = 'S001'"
        ).fetchone()
        assert row is not None
        assert int(row[0] or 0) == int(prog_id)
        assert (row[1] or "") == "AI"
        assert (row[2] or "") == "خريف 25-26"

        lg = db_conn.execute(
            """
            SELECT action, details FROM activity_log
            WHERE action = 'student_specialization_update'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        assert lg is not None
        assert "student_id=S001" in (lg[1] or "")

    def test_specialization_summary_returns_counts(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code = f"SD{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "قسم إحصاء", "Summary Dept"),
        )
        dep_id = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        cur.execute(
            """
            INSERT INTO programs (department_id, code, name_ar, phase, is_active)
            VALUES (?, 'SUM01', 'برنامج إحصاء', 'major', 1)
            """,
            (dep_id,),
        )
        prog_id = cur.execute("SELECT id FROM programs WHERE department_id = ? ORDER BY id DESC LIMIT 1", (dep_id,)).fetchone()[0]
        sid = f"SS{uid}"
        cur.execute(
            """
            INSERT INTO students (student_id, student_name, enrollment_status, department_id, current_program_id, track_code)
            VALUES (?, 'طالب مسار', 'active', ?, ?, 'DATA')
            """,
            (sid, dep_id, prog_id),
        )
        db_conn.commit()

        with app.test_client() as c:
            lr = c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
            assert lr.status_code == 200
            r = c.get("/students/specialization/summary")
            assert r.status_code == 200
            j = r.get_json()
            assert j.get("status") == "ok"
            totals = j.get("totals") or {}
            assert int(totals.get("students") or 0) >= 1
            rows = j.get("by_program_track") or []
            assert any((x.get("track_code") or "") == "DATA" for x in rows)

