"""سياق قسم المسؤول: الجلسة وواجهة التصفية."""
import uuid


class TestAdminDepartmentScope:
    def test_auth_check_includes_scope_null_for_admin(self, app):
        with app.test_client() as c:
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            r = c.get("/auth/check")
            assert r.status_code == 200
            data = r.get_json()
            assert data.get("admin_department_scope") is None
            assert data.get("capabilities", {}).get("can_switch_department_scope") is True

    def test_set_scope_requires_department_row(self, app, db_conn):
        code = "TSC" + uuid.uuid4().hex[:8].upper()
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "قسم تجربة", "Scope Dept"),
        )
        db_conn.commit()
        did = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]

        with app.test_client() as c:
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            pr = c.post(
                "/auth/admin_department_scope",
                json={"department_id": did},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert pr.status_code == 200
            pj = pr.get_json()
            assert pj.get("status") == "ok"
            assert pj.get("admin_department_scope", {}).get("id") == did

            chk = c.get("/auth/check")
            assert chk.get_json().get("admin_department_scope", {}).get("code") == code

            clr = c.post(
                "/auth/admin_department_scope",
                json={"department_id": None},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert clr.status_code == 200
            assert clr.get_json().get("admin_department_scope") is None

    def test_set_scope_forbidden_for_student(self, app, student_auth_client):
        resp = student_auth_client.post(
            "/auth/admin_department_scope",
            json={"department_id": 1},
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 403

    def test_scope_status_unscoped(self, app):
        with app.test_client() as c:
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            r = c.get("/auth/admin_department_scope/status")
            assert r.status_code == 200
            data = r.get_json()
            assert data.get("status") == "ok"
            assert data.get("scoped") is False
            assert data.get("is_empty") is False

    def test_scope_status_reports_empty_department(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code = f"EM{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "قسم فارغ", "Empty"),
        )
        db_conn.commit()
        did = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        with app.test_client() as c:
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            c.post(
                "/auth/admin_department_scope",
                json={"department_id": did},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            r = c.get("/auth/admin_department_scope/status")
            assert r.status_code == 200
            data = r.get_json()
            assert data.get("scoped") is True
            assert data.get("student_count") == 0
            assert data.get("is_empty") is True

    def test_scope_status_counts_students_in_department(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code = f"SC{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "قسم عد", "Count"),
        )
        db_conn.commit()
        did = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
        sid = f"ST{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (sid, "طالب عد", did),
        )
        db_conn.commit()
        with app.test_client() as c:
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            c.post(
                "/auth/admin_department_scope",
                json={"department_id": did},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            r = c.get("/auth/admin_department_scope/status")
            assert r.status_code == 200
            data = r.get_json()
            assert data.get("student_count") >= 1
            assert data.get("is_empty") is False

    def test_users_list_respects_department_scope(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"DA{uid}".upper()[:12]
        code2 = f"DB{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code1, "قسم أ", "A"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code2, "قسم ب", "B"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        sid_a = f"S1{uid}"
        sid_b = f"S2{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (sid_a, "موظف اختبار أ", d1),
        )
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (sid_b, "موظف اختبار ب", d2),
        )
        ph = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        ua = f"stu_scope_a_{uid}"
        ub = f"stu_scope_b_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, student_id, department_id) VALUES (?, ?, 'student', ?, ?)",
            (ua, ph, sid_a, d1),
        )
        cur.execute(
            "INSERT INTO users (username, password_hash, role, student_id, department_id) VALUES (?, ?, 'student', ?, ?)",
            (ub, ph, sid_b, d2),
        )
        db_conn.commit()

        with app.test_client() as c:
            c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
            c.post(
                "/auth/admin_department_scope",
                json={"department_id": d1},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            r = c.get("/users/list")
            assert r.status_code == 200
            users = r.get_json().get("users") or []
            names = {u.get("username") for u in users}
            assert ua in names
            assert ub not in names
            c.post(
                "/auth/admin_department_scope",
                json={"department_id": None},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )


class TestInstructorsDepartmentScope:
    def test_instructors_list_full_when_admin_has_no_scope(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"IA{uid}".upper()[:12]
        code2 = f"IB{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code1, "قسم أ", "A"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code2, "قسم ب", "B"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        cur.execute(
            "INSERT INTO instructors (name, type, email, is_active, department_id) VALUES (?, 'internal', NULL, 1, ?)",
            (f"Prof A {uid}", d1),
        )
        cur.execute(
            "INSERT INTO instructors (name, type, email, is_active, department_id) VALUES (?, 'internal', NULL, 1, ?)",
            (f"Prof B {uid}", d2),
        )
        db_conn.commit()

        with app.test_client() as c:
            c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
            r = c.get("/instructors/list")
            assert r.status_code == 200
            insts = r.get_json().get("instructors") or []
            names = {i.get("name") for i in insts}
            assert f"Prof A {uid}" in names
            assert f"Prof B {uid}" in names

    def test_instructors_list_respects_department_scope(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"IC{uid}".upper()[:12]
        code2 = f"ID{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code1, "قسم أ", "A"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code2, "قسم ب", "B"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        cur.execute(
            "INSERT INTO instructors (name, type, email, is_active, department_id) VALUES (?, 'internal', NULL, 1, ?)",
            (f"Scoped A {uid}", d1),
        )
        cur.execute(
            "INSERT INTO instructors (name, type, email, is_active, department_id) VALUES (?, 'internal', NULL, 1, ?)",
            (f"Scoped B {uid}", d2),
        )
        db_conn.commit()

        with app.test_client() as c:
            c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
            c.post(
                "/auth/admin_department_scope",
                json={"department_id": d1},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            r = c.get("/instructors/list")
            assert r.status_code == 200
            insts = r.get_json().get("instructors") or []
            names = {i.get("name") for i in insts}
            assert f"Scoped A {uid}" in names
            assert f"Scoped B {uid}" not in names
            c.post(
                "/auth/admin_department_scope",
                json={"department_id": None},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )

    def test_instructors_save_delete_forbidden_out_of_scope(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"IE{uid}".upper()[:12]
        code2 = f"IF{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code1, "قسم أ", "A"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code2, "قسم ب", "B"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        cur.execute(
            "INSERT INTO instructors (name, type, email, is_active, department_id) VALUES (?, 'internal', NULL, 1, ?)",
            (f"Other dept {uid}", d2),
        )
        iid = int(cur.lastrowid)
        db_conn.commit()
        headers = {"Content-Type": "application/json", "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}

        with app.test_client() as c:
            c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
            c.post(
                "/auth/admin_department_scope",
                json={"department_id": d1},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            up = c.post(
                "/instructors/save",
                json={"id": iid, "name": f"Renamed {uid}", "type": "internal", "is_active": True},
                headers=headers,
            )
            assert up.status_code == 403
            de = c.post("/instructors/delete", json={"id": iid}, headers=headers)
            assert de.status_code == 403
            c.post(
                "/auth/admin_department_scope",
                json={"department_id": None},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )

    def test_admin_main_can_change_primary_department_even_with_scope(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"IG{uid}".upper()[:12]
        code2 = f"IH{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code1, "قسم أ", "A"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code2, "قسم ب", "B"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        cur.execute(
            "INSERT INTO instructors (name, type, email, is_active, department_id) VALUES (?, 'internal', NULL, 1, ?)",
            (f"Move dept {uid}", d1),
        )
        iid = int(cur.lastrowid)
        db_conn.commit()
        headers = {"Content-Type": "application/json", "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}

        with app.test_client() as c:
            c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
            c.post(
                "/auth/admin_department_scope",
                json={"department_id": d1},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            up = c.post(
                "/instructors/save",
                json={
                    "id": iid,
                    "name": f"Move dept {uid}",
                    "type": "internal",
                    "is_active": True,
                    "department_id": d2,
                },
                headers=headers,
            )
            assert up.status_code == 200
            row = db_conn.execute("SELECT department_id FROM instructors WHERE id = ?", (iid,)).fetchone()
            assert int(row[0]) == int(d2)


class TestHeadDepartmentIsolation:
    def test_head_mode_students_list_is_scoped_to_department(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"HC{uid}".upper()[:12]
        code2 = f"HM{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code1, "مدني", "Civil"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code2, "ميكانيك", "Mechanical"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        s1 = f"SC{uid}"
        s2 = f"SM{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (s1, "طالب مدني", d1),
        )
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (s2, "طالب ميكانيك", d2),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_civil_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, d1),
        )
        db_conn.commit()

        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            r = c.get("/students/list")
            assert r.status_code == 200
            arr = r.get_json() or []
            ids = {x.get("student_id") for x in arr}
            assert s1 in ids
            assert s2 not in ids

    def test_head_mode_schedule_rows_is_scoped_to_department(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"SC{uid}".upper()[:12]
        code2 = f"SM{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code1, "مدني", "Civil"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code2, "ميكانيك", "Mechanical"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        cur.execute(
            """
            INSERT INTO schedule (course_name, department_id, day, time, room, instructor, semester)
            VALUES ('Statics-C', ?, 'الأحد', '08:00-09:00', 'R1', 'I1', 'خريف 25-26')
            """,
            (d1,),
        )
        cur.execute(
            """
            INSERT INTO schedule (course_name, department_id, day, time, room, instructor, semester)
            VALUES ('Statics-M', ?, 'الأحد', '10:00-11:00', 'R2', 'I2', 'خريف 25-26')
            """,
            (d2,),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_sched_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, d1),
        )
        db_conn.commit()

        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            r = c.get("/schedule/rows")
            assert r.status_code == 200
            rows = r.get_json() or []
            names = {x.get("course_name") for x in rows}
            assert "Statics-C" in names
            assert "Statics-M" not in names

    def test_head_mode_courses_list_is_scoped_to_department(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"CC{uid}".upper()[:12]
        code2 = f"CM{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code1, "مدني", "Civil"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code2, "ميكانيك", "Mechanical"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        cur.execute(
            """
            INSERT OR REPLACE INTO courses
            (course_name, course_code, units, category, owning_department_id)
            VALUES ('CivilCourse', 'CIV101', 3, 'required', ?)
            """,
            (d1,),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO courses
            (course_name, course_code, units, category, owning_department_id)
            VALUES ('MechCourse', 'MEC101', 3, 'required', ?)
            """,
            (d2,),
        )
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_course_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, d1),
        )
        db_conn.commit()

        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            r = c.get("/courses/list")
            assert r.status_code == 200
            arr = r.get_json() or []
            names = {x.get("course_name") for x in arr}
            assert "CivilCourse" in names
            assert "MechCourse" not in names

    def test_head_mode_transcript_for_other_department_forbidden(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"TC{uid}".upper()[:12]
        code2 = f"TM{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code1, "مدني", "Civil"))
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code2, "ميكانيك", "Mechanical"))
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        s1 = f"TXC{uid}"
        s2 = f"TXM{uid}"
        cur.execute("INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)", (s1, "طالب مدني", d1))
        cur.execute("INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)", (s2, "طالب ميكانيك", d2))
        pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
        head_user = f"head_tr_{uid}"
        cur.execute("INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)", (head_user, pw, d1))
        db_conn.commit()
        with app.test_client() as c:
            assert c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}).status_code == 200
            ok = c.get(f"/grades/transcript/{s1}")
            bad = c.get(f"/grades/transcript/{s2}")
            assert ok.status_code == 200
            assert bad.status_code == 403

    def test_head_mode_enrollment_plans_list_scoped(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"PC{uid}".upper()[:12]
        code2 = f"PM{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code1, "مدني", "Civil"))
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code2, "ميكانيك", "Mechanical"))
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        s1 = f"EPC{uid}"
        s2 = f"EPM{uid}"
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS enrollment_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                semester TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Draft',
                rejection_reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS enrollment_plan_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id INTEGER NOT NULL,
                course_name TEXT NOT NULL
            )
            """
        )
        cur.execute("INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)", (s1, "طالب مدني", d1))
        cur.execute("INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)", (s2, "طالب ميكانيك", d2))
        cur.execute(
            "INSERT INTO enrollment_plans (student_id, semester, status, created_at, updated_at) VALUES (?, 'خريف 25-26', 'Draft', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (s1,),
        )
        cur.execute(
            "INSERT INTO enrollment_plans (student_id, semester, status, created_at, updated_at) VALUES (?, 'خريف 25-26', 'Draft', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (s2,),
        )
        pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
        head_user = f"head_pl_{uid}"
        cur.execute("INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)", (head_user, pw, d1))
        db_conn.commit()
        with app.test_client() as c:
            assert c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}).status_code == 200
            r = c.get("/enrollment/plans")
            assert r.status_code == 200
            plans = r.get_json().get("plans") or []
            sids = {p.get("student_id") for p in plans}
            assert s1 in sids
            assert s2 not in sids

    def test_academic_calendar_update_forbidden_for_head(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"AC{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS academic_calendar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                academic_year TEXT NOT NULL,
                term TEXT NOT NULL,
                item_no INTEGER NOT NULL,
                title TEXT NOT NULL,
                event_date TEXT,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(academic_year, term, item_no)
            )
            """
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code1, "مدني", "Civil"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
        head_user = f"head_cal_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, d1),
        )
        db_conn.commit()
        with app.test_client() as c:
            assert c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}).status_code == 200
            r = c.post(
                "/academic_calendar/items",
                json={
                    "academic_year": "2025/2026",
                    "term": "fall",
                    "items": [{"item_no": 1, "title": "تجربة", "event_date": "2026-01-01"}],
                },
            )
            assert r.status_code == 403

    def test_head_mode_exam_rows_scoped_by_course_department(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"EC{uid}".upper()[:12]
        code2 = f"EM{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS exams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_type TEXT NOT NULL,
                exam_id INTEGER,
                course_name TEXT NOT NULL,
                exam_date TEXT,
                exam_time TEXT,
                room TEXT,
                instructor TEXT
            )
            """
        )
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code1, "مدني", "Civil"))
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code2, "ميكانيك", "Mechanical"))
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        cur.execute(
            "INSERT OR REPLACE INTO courses (course_name, course_code, units, category, owning_department_id) VALUES ('ExamCivil', 'EC101', 3, 'required', ?)",
            (d1,),
        )
        cur.execute(
            "INSERT OR REPLACE INTO courses (course_name, course_code, units, category, owning_department_id) VALUES ('ExamMech', 'EM101', 3, 'required', ?)",
            (d2,),
        )
        cur.execute(
            "INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor) VALUES ('midterm', NULL, 'ExamCivil', '2026-01-10', '09:00-11:00', 'R1', 'I1')"
        )
        cur.execute(
            "INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor) VALUES ('midterm', NULL, 'ExamMech', '2026-01-10', '11:00-13:00', 'R2', 'I2')"
        )
        pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
        head_user = f"head_exam_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, d1),
        )
        db_conn.commit()
        with app.test_client() as c:
            assert c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}).status_code == 200
            r = c.get("/exams/midterm/rows")
            assert r.status_code == 200
            rows = r.get_json() or []
            names = {x.get("course_name") for x in rows}
            assert "ExamCivil" in names
            assert "ExamMech" not in names

    def test_head_course_registration_counts_scoped_to_department(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"RCC{uid}".upper()[:12]
        code2 = f"RCM{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code1, "مدني", "Civil"))
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code2, "ميكانيك", "Mechanical"))
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        s1 = f"RCSa{uid}"
        s2 = f"RSb{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (s1, "طالب مدني", d1),
        )
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (s2, "طالب ميكانيك", d2),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO courses
            (course_name, course_code, units, category, owning_department_id)
            VALUES ('RegCivil', ?, 3, 'required', ?)
            """,
            (f"C{uid[:4]}", d1),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO courses
            (course_name, course_code, units, category, owning_department_id)
            VALUES ('RegMech', ?, 3, 'required', ?)
            """,
            (f"M{uid[:4]}", d2),
        )
        cur.execute("INSERT INTO registrations (student_id, course_name) VALUES (?, ?)", (s1, "RegCivil"))
        cur.execute("INSERT INTO registrations (student_id, course_name) VALUES (?, ?)", (s2, "RegMech"))
        pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
        head_user = f"head_regcount_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, d1),
        )
        db_conn.commit()
        headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
        with app.test_client() as c:
            assert c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}).status_code == 200
            r = c.get("/students/course_registration_counts", headers=headers)
            assert r.status_code == 200
            body = r.get_json()
            items = body.get("items") or []
            codes = {(it.get("course_code") or "").strip() for it in items}
            names = {(it.get("course_name") or "").strip() for it in items}
            assert "RegCivil" in names
            assert "RegMech" not in names
            summary = body.get("summary") or {}
            assert int(summary.get("distinct_students_with_registration") or 0) >= 1

    def test_head_performance_report_and_status_scoped(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"PCC{uid}".upper()[:12]
        code2 = f"PCM{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code1, "مدني", "Civil"))
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code2, "ميكانيك", "Mechanical"))
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        s1 = f"PSa{uid}"
        s2 = f"PSb{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (s1, "طالب مدني", d1),
        )
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (s2, "طالب ميكانيك", d2),
        )
        pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
        head_user = f"head_perf_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, d1),
        )
        db_conn.commit()
        headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
        with app.test_client() as c:
            assert c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}).status_code == 200
            r = c.get("/performance/report", headers=headers)
            assert r.status_code == 200
            students = r.get_json().get("students") or []
            ids = {x.get("student_id") for x in students}
            assert s1 in ids
            assert s2 not in ids
            assert c.get(f"/performance/status/{s1}", headers=headers).status_code == 200
            assert c.get(f"/performance/status/{s2}", headers=headers).status_code == 403

    def test_head_admin_summary_counts_scoped(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"ASC{uid}".upper()[:12]
        code2 = f"ASM{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code1, "مدني", "Civil"))
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code2, "ميكانيك", "Mechanical"))
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (f"ASa{uid}", "مدني واحد", d1),
        )
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (f"ASb{uid}", "ميكانيك واحد", d2),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO courses
            (course_name, course_code, units, category, owning_department_id)
            VALUES ('SumCivil', ?, 3, 'required', ?)
            """,
            (f"SC{uid[:4]}", d1),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO courses
            (course_name, course_code, units, category, owning_department_id)
            VALUES ('SumMech', ?, 3, 'required', ?)
            """,
            (f"SM{uid[:4]}", d2),
        )
        pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
        head_user = f"head_sum_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, d1),
        )
        db_conn.commit()
        headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
        with app.test_client() as c:
            assert c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}).status_code == 200
            r = c.get("/admin/summary", headers=headers)
            assert r.status_code == 200
            data = (r.get_json() or {}).get("data") or {}
            expected_students = db_conn.execute(
                """
                SELECT COUNT(*) FROM students
                WHERE department_id = ?
                   OR current_program_id IN (SELECT id FROM programs WHERE department_id = ?)
                   OR admission_program_id IN (SELECT id FROM programs WHERE department_id = ?)
                """,
                (int(d1), int(d1), int(d1)),
            ).fetchone()[0]
            expected_courses = db_conn.execute(
                "SELECT COUNT(*) FROM courses WHERE COALESCE(owning_department_id,-1) = ?",
                (int(d1),),
            ).fetchone()[0]
            assert int(data.get("students") or 0) == int(expected_students or 0)
            assert int(data.get("courses") or 0) == int(expected_courses or 0)

    def test_head_results_data_scopes_conflicts_and_schedule(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        code1 = f"RQ{uid}".upper()[:12]
        code2 = f"RM{uid}".upper()[:12]
        cur = db_conn.cursor()
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code1, "مدني", "Civil"))
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code2, "ميكانيك", "Mechanical"))
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        rs1 = f"RCS{uid}"
        rs2 = f"RCS2{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (rs1, "طالب مدني", d1),
        )
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (rs2, "طالب آخر قسم", d2),
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS conflict_report (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                day TEXT,
                time TEXT,
                conflicting_sections TEXT,
                detected_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            "INSERT INTO conflict_report (student_id, day, time, conflicting_sections) VALUES (?,?,?,?)",
            (rs1, "الأحد", "08:00-09:00", "اختبار تعارض مدني"),
        )
        cur.execute(
            "INSERT INTO conflict_report (student_id, day, time, conflicting_sections) VALUES (?,?,?,?)",
            (rs2, "الأحد", "10:00-11:00", "اختبار تعارض ميكانيك"),
        )
        cur.execute(
            """
            INSERT INTO schedule (course_name, department_id, day, time, room, instructor, semester)
            VALUES (?, ?, 'الاثنين', '09:00-10:00', 'R1', 'Prof1', 'خريف 25-26')
            """,
            (f"SchedCivil{uid}", d1),
        )
        cur.execute(
            """
            INSERT INTO schedule (course_name, department_id, day, time, room, instructor, semester)
            VALUES (?, ?, 'الاثنين', '11:00-12:00', 'R2', 'Prof2', 'خريف 25-26')
            """,
            (f"SchedMech{uid}", d2),
        )
        pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
        head_user = f"head_res_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, d1),
        )
        db_conn.commit()
        headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
        with app.test_client() as c:
            assert c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}).status_code == 200
            r = c.get("/results_data", headers=headers)
            assert r.status_code == 200
            data = r.get_json()
            crs = data.get("conflict_report") or []
            assert len([x for x in crs if x.get("student_id") == rs1]) >= 1
            assert len([x for x in crs if x.get("student_id") == rs2]) == 0
            opt = data.get("optimized_schedule") or []
            cnames = {str(x.get("course_name") or "").strip() for x in opt}
            assert f"SchedCivil{uid}" in cnames
            assert f"SchedMech{uid}" not in cnames

    def test_head_exam_schedule_coverage_scoped_vs_college_wide(self, app, db_conn):
        """مقارنة التسجيل/الجدولة مع امتحانات القسم لا تُحمّى بيانات كل الأقسام."""
        uid = uuid.uuid4().hex[:8]
        code1 = f"ECC{uid}".upper()[:12]
        code2 = f"ECM{uid}".upper()[:12]
        sem = "خريف 44-45"
        cur = db_conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS exams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_type TEXT NOT NULL,
                exam_id INTEGER,
                course_name TEXT NOT NULL,
                exam_date TEXT,
                exam_time TEXT,
                room TEXT,
                instructor TEXT
            )
            """
        )
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code1, "مدني", "Civil"))
        cur.execute("INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)", (code2, "ميكانيك", "Mechanical"))
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (code1,)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (code2,)).fetchone()[0]
        c_civ = f"CovCivCourse{uid}"
        c_mec = f"CovMechCourse{uid}"
        cur.execute(
            """
            INSERT OR REPLACE INTO courses
            (course_name, course_code, units, category, owning_department_id)
            VALUES (?, ?, 3, 'required', ?)
            """,
            (c_civ, f"CC{uid[:4]}", d1),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO courses
            (course_name, course_code, units, category, owning_department_id)
            VALUES (?, ?, 3, 'required', ?)
            """,
            (c_mec, f"CM{uid[:4]}", d2),
        )
        sid1 = f"ECS1{uid}"
        sid2 = f"ECS2{uid}"
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (sid1, "طالب ضمن مقارنة الامتحانات أ", d1),
        )
        cur.execute(
            "INSERT INTO students (student_id, student_name, enrollment_status, department_id) VALUES (?, ?, 'active', ?)",
            (sid2, "طالب ضمن مقارنة الامتحانات ب", d2),
        )
        cur.execute(
            """
            INSERT INTO schedule (course_name, department_id, day, time, room, instructor, semester)
            VALUES (?, ?, 'الأحد', '08:00-09:30', 'Rcv1', 'Icv', ?)
            """,
            (c_civ, d1, sem),
        )
        cur.execute(
            """
            INSERT INTO schedule (course_name, department_id, day, time, room, instructor, semester)
            VALUES (?, ?, 'الثلاثاء', '10:00-11:30', 'Rcv2', 'Icv2', ?)
            """,
            (c_mec, d2, sem),
        )
        cur.execute("INSERT INTO registrations (student_id, course_name) VALUES (?, ?)", (sid1, c_civ))
        cur.execute("INSERT INTO registrations (student_id, course_name) VALUES (?, ?)", (sid2, c_mec))
        cur.execute(
            "INSERT INTO exams (exam_type, course_name, exam_date, exam_time) VALUES ('midterm', ?, '2026-05-01', '09:00')",
            (c_civ,),
        )
        cur.execute(
            "INSERT INTO exams (exam_type, course_name, exam_date, exam_time) VALUES ('midterm', ?, '2026-05-02', '11:00')",
            (c_mec,),
        )
        pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
        head_user = f"head_ecov_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, d1),
        )
        db_conn.commit()
        headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
        with app.test_client() as c:
            assert c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"}).status_code == 200
            r = c.get("/exams/midterm/schedule_coverage", headers=headers)
            assert r.status_code == 200
            cov = r.get_json() or {}
            counts = cov.get("counts") or {}
            assert int(counts.get("registrations_distinct") or 0) == 1
            assert int(counts.get("schedule_distinct") or 0) == 1
            assert int(counts.get("exam_distinct_courses") or 0) == 1
            baseline = cov.get("registration_baseline") or {}
            miss = baseline.get("missing_in_exam") or []
            assert c_civ not in miss
            assert c_mec not in miss

