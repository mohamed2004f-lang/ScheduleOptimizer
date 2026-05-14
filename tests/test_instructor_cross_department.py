"""إسناد الأستاذ لأكثر من قسم وتكافؤ المقررات — ترحيل وAPI."""
import uuid


class TestInstructorCrossDepartmentApi:
    def test_instructors_list_includes_departments_array(self, auth_client):
        r = auth_client.get("/instructors/list")
        assert r.status_code == 200
        insts = r.get_json().get("instructors") or []
        assert isinstance(insts, list)
        for x in insts:
            assert "departments" in x
            assert isinstance(x["departments"], list)

    def test_get_department_assignments_ok(self, auth_client):
        r = auth_client.get("/instructors/1/department_assignments")
        assert r.status_code == 200
        j = r.get_json()
        assert j.get("status") == "ok"
        assert isinstance(j.get("assignments"), list)

    def test_course_equivalence_groups_api(self, auth_client):
        r = auth_client.get("/course_equivalences/groups")
        assert r.status_code == 200
        assert r.get_json().get("status") == "ok"

    def test_save_external_scope_and_change_primary_department(self, auth_client, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"XA{uid}".upper()[:12], "قسم أ", "A"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"XB{uid}".upper()[:12], "قسم ب", "B"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (f"XA{uid}".upper()[:12],)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (f"XB{uid}".upper()[:12],)).fetchone()[0]
        cur.execute(
            "INSERT INTO instructors (name, type, email, is_active, department_id) VALUES (?, 'external', NULL, 1, ?)",
            (f"Ext {uid}", d1),
        )
        iid = int(cur.lastrowid)
        db_conn.commit()

        r = auth_client.post(
            "/instructors/save",
            json={
                "id": iid,
                "name": f"Ext {uid}",
                "type": "external",
                "is_active": True,
                "department_id": d2,
                "external_scope": "outside_university",
            },
            headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        assert r.status_code == 200

        row = db_conn.execute(
            "SELECT department_id, external_scope FROM instructors WHERE id = ?", (iid,)
        ).fetchone()
        assert int(row[0]) == int(d2)
        assert (row[1] or "") == "outside_university"

    def test_equivalence_expand_and_students_by_department(self, app, auth_client, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"EQ{uid}".upper()[:12], "قسم تكافؤ", "EQ"),
        )
        db_conn.commit()
        did = cur.execute(
            "SELECT id FROM departments WHERE code = ?", (f"EQ{uid}".upper()[:12],)
        ).fetchone()[0]

        cur.execute(
            "INSERT INTO course_equivalence_groups (group_key, title, is_active) VALUES (?, ?, 1)",
            (f"g_{uid}", "مجموعة تجربة"),
        )
        db_conn.commit()
        gid = cur.execute(
            "SELECT id FROM course_equivalence_groups WHERE group_key = ?", (f"g_{uid}",)
        ).fetchone()[0]

        cur.execute(
            """
            INSERT INTO course_equivalence_items
            (group_id, department_id, course_name, course_code, is_active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (gid, did, "رياضيات 1", "X1"),
        )
        cur.execute(
            """
            INSERT INTO course_equivalence_items
            (group_id, department_id, course_name, course_code, is_active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (gid, did, "رياضيات موازي", "X2"),
        )
        db_conn.commit()

        cur.execute(
            "UPDATE students SET department_id = ? WHERE student_id = 'S001'", (did,)
        )
        cur.execute(
            "INSERT OR REPLACE INTO registrations (student_id, course_name) VALUES ('S001', 'رياضيات موازي')"
        )
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor, instructor_id, semester, department_id)
            VALUES ('رياضيات 1', 'الأحد', '08:00-09:30', 'قاعة', 'أستاذ تجريبي', 1, 'خريف 44-45', ?)
            """,
            (did,),
        )
        try:
            cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
        except Exception:
            pass
        db_conn.commit()

        r = auth_client.get(
            f"/instructors/1/students_by_department?department_id={did}&semester=خريف 44-45"
        )
        assert r.status_code == 200
        j = r.get_json()
        assert j.get("status") == "ok"
        studs = j.get("students") or []
        ids = {s.get("student_id") for s in studs}
        assert "S001" in ids
        crs = j.get("course_names_resolved") or []
        assert "رياضيات 1" in crs and "رياضيات موازي" in crs
