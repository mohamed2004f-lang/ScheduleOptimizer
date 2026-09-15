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


class TestInstructorLinkUnlinkAndListFields:
    def test_list_includes_relation_fields(self, auth_client):
        r = auth_client.get("/instructors/list")
        assert r.status_code == 200
        insts = r.get_json().get("instructors") or []
        assert isinstance(insts, list)
        for x in insts:
            assert "relation_to_scope" in x
            assert "can_manage_identity" in x
            assert "can_unlink_from_scope" in x

    def test_offering_instructors_include_collaborator(self, db_conn):
        from backend.services.term_offerings import _list_offering_instructors
        from backend.repositories.instructor_assignments_repo import upsert_user_assignment

        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"OA{uid}".upper()[:12], "عرض1", "O1"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"OB{uid}".upper()[:12], "عرض2", "O2"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (f"OA{uid}".upper()[:12],)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (f"OB{uid}".upper()[:12],)).fetchone()[0]
        cur.execute(
            "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
            (f"OfferCollab {uid}", d1),
        )
        iid = int(cur.lastrowid)
        upsert_user_assignment(db_conn, instructor_id=iid, department_id=int(d2))
        db_conn.commit()
        rows = _list_offering_instructors(db_conn, int(d2))
        found = next((r for r in rows if int(r["id"]) == iid), None)
        assert found is not None
        assert found.get("relation") == "collaborator"

    def test_hod_sees_collaborator_and_can_unlink(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"LA{uid}".upper()[:12], "منزل ربط", "HomeL"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"LB{uid}".upper()[:12], "مضيف ربط", "HostL"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (f"LA{uid}".upper()[:12],)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (f"LB{uid}".upper()[:12],)).fetchone()[0]
        cur.execute(
            "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
            (f"Collab {uid}", d1),
        )
        iid = int(cur.lastrowid)
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        host_user = f"hod_link_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (host_user, pw, d2),
        )
        db_conn.commit()

        with app.test_client() as c:
            assert c.post("/auth/login", json={"username": host_user, "password": "TestP@ssw0rd!"}).status_code == 200
            link = c.post(
                f"/instructors/{iid}/link_department",
                json={},
                headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert link.status_code == 200, link.get_data(as_text=True)

            lst = c.get("/instructors/list")
            assert lst.status_code == 200
            found = next((x for x in (lst.get_json().get("instructors") or []) if int(x["id"]) == iid), None)
            assert found is not None
            assert found.get("relation_to_scope") == "collaborator"
            assert found.get("can_manage_identity") is False
            assert found.get("can_unlink_from_scope") is True

            bad_del = c.post(
                "/instructors/delete",
                json={"id": iid},
                headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert bad_del.status_code == 403

            un = c.post(
                f"/instructors/{iid}/unlink_department",
                json={},
                headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert un.status_code == 200
            lst2 = c.get("/instructors/list")
            ids = {int(x["id"]) for x in (lst2.get_json().get("instructors") or [])}
            assert iid not in ids

    def test_hod_can_save_cross_department_coop_for_home_instructor(self, app, db_conn):
        """رئيس القسم يملك هوية الأستاذ يجوز إسناد أقسام متعاونة خارج نطاقه."""
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"HA{uid}".upper()[:12], "منزل حفظ", "HomeS"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"HB{uid}".upper()[:12], "تعاون حفظ", "CoopS"),
        )
        d_home = cur.execute(
            "SELECT id FROM departments WHERE code = ?", (f"HA{uid}".upper()[:12],)
        ).fetchone()[0]
        d_coop = cur.execute(
            "SELECT id FROM departments WHERE code = ?", (f"HB{uid}".upper()[:12],)
        ).fetchone()[0]
        cur.execute(
            "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
            (f"HomeInst {uid}", d_home),
        )
        iid = int(cur.lastrowid)
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        hod = f"hod_save_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (hod, pw, d_home),
        )
        db_conn.commit()

        with app.test_client() as c:
            assert c.post("/auth/login", json={"username": hod, "password": "TestP@ssw0rd!"}).status_code == 200
            save = c.post(
                f"/instructors/{iid}/department_assignments/save",
                json={"assignments": [{"department_id": int(d_coop)}]},
                headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert save.status_code == 200, save.get_data(as_text=True)
            assert (save.get_json() or {}).get("status") == "ok"
            saved = (save.get_json() or {}).get("assignments") or []
            assert any(int(a["department_id"]) == int(d_coop) for a in saved)

            opts = c.get("/instructors/department/options")
            assert opts.status_code == 200, opts.get_data(as_text=True)
            opt_ids = {int(x["id"]) for x in (opts.get_json().get("items") or [])}
            assert int(d_coop) in opt_ids
            assert int(d_home) in opt_ids

            # إزالة قسم متعاون (قائمة فارغة) يجب أن تنجح أيضاً
            clear = c.post(
                f"/instructors/{iid}/department_assignments/save",
                json={"assignments": []},
                headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert clear.status_code == 200, clear.get_data(as_text=True)
