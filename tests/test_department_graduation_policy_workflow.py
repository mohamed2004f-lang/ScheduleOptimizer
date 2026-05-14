import uuid

from werkzeug.security import generate_password_hash

from backend.services.registration_policy import student_graduation_plan


class TestDepartmentGraduationPolicyWorkflow:
    def test_head_propose_then_admin_main_approve(self, app, db_conn):
        cur = db_conn.cursor()
        uid = uuid.uuid4().hex[:8]
        dep_code = f"DP{uid}".upper()[:12]
        head_user = f"head_{uid}"
        main_user = f"main_{uid}"
        pw_hash = generate_password_hash("TestP@ssw0rd!")

        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (dep_code, "قسم اختبار سياسات", "Policy Dept"),
        )
        dep_id = cur.execute("SELECT id FROM departments WHERE code = ?", (dep_code,)).fetchone()[0]
        cur.execute(
            """
            INSERT INTO instructors (name, department_id, type, email, is_active)
            VALUES (?, ?, 'internal', ?, 1)
            """,
            ("رئيس قسم اختبار", dep_id, f"head_{uid}@example.com"),
        )
        inst_id = cur.execute(
            "SELECT id FROM instructors WHERE email = ? LIMIT 1",
            (f"head_{uid}@example.com",),
        ).fetchone()[0]
        cur.execute(
            """
            INSERT INTO users (username, password_hash, role, instructor_id, department_id)
            VALUES (?, ?, 'head_of_department', ?, ?)
            """,
            (head_user, pw_hash, inst_id, dep_id),
        )
        cur.execute(
            """
            INSERT INTO users (username, password_hash, role)
            VALUES (?, ?, 'admin_main')
            """,
            (main_user, pw_hash),
        )
        db_conn.commit()

        with app.test_client() as c:
            lr1 = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lr1.status_code == 200

            rp = c.post(
                "/department_policies/head/propose",
                json={
                    "plan_code": "155",
                    "min_total_units": 155,
                    "effective_from_term": "خريف",
                    "effective_from_year": "2025",
                    "notes": "اقتراح رئيس القسم",
                },
            )
            assert rp.status_code == 200
            pid = int((rp.get_json() or {}).get("id") or 0)
            assert pid > 0

            rs = c.post(f"/department_policies/head/submit/{pid}")
            assert rs.status_code == 200

            c.post("/auth/logout")
            lr2 = c.post("/auth/login", json={"username": main_user, "password": "TestP@ssw0rd!"})
            assert lr2.status_code == 200

            ra = c.post(f"/department_policies/admin/approve/{pid}", json={"activate_now": True})
            assert ra.status_code == 200

            active = c.get(f"/department_policies/active/{dep_id}")
            assert active.status_code == 200
            item = (active.get_json() or {}).get("item") or {}
            assert (item.get("status") or "") == "approved"
            assert (item.get("plan_code") or "") == "155"
            assert int(item.get("min_total_units") or 0) == 155
            assert (item.get("effective_from_term") or "").strip() != ""

    def test_student_plan_falls_back_to_department_approved_policy(self, db_conn):
        cur = db_conn.cursor()
        uid = uuid.uuid4().hex[:8]
        dep_code = f"FP{uid}".upper()[:12]
        sid = f"SP{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (dep_code, "قسم fallback", "Fallback Dept"),
        )
        dep_id = cur.execute("SELECT id FROM departments WHERE code = ?", (dep_code,)).fetchone()[0]
        cur.execute(
            """
            INSERT INTO students (student_id, student_name, department_id, graduation_plan, enrollment_status)
            VALUES (?, 'طالب سياسة قسم', ?, '', 'active')
            """,
            (sid, dep_id),
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS department_graduation_policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_id INTEGER NOT NULL,
                plan_code TEXT NOT NULL,
                min_total_units INTEGER NOT NULL DEFAULT 0,
                effective_from_term TEXT DEFAULT '',
                effective_from_year TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                submitted_at TEXT,
                approved_at TEXT,
                rejected_at TEXT,
                rejection_reason TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                approved_by TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            INSERT INTO department_graduation_policies
            (department_id, plan_code, min_total_units, status, approved_at)
            VALUES (?, '150', 150, 'approved', CURRENT_TIMESTAMP)
            """,
            (dep_id,),
        )
        db_conn.commit()

        detected = student_graduation_plan(cur, sid)
        assert detected == "150"

    def test_student_plan_uses_current_effective_policy_not_future(self, db_conn):
        cur = db_conn.cursor()
        uid = uuid.uuid4().hex[:8]
        dep_code = f"EF{uid}".upper()[:12]
        sid = f"SE{uid}".upper()[:12]
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (dep_code, "قسم سريان", "Effective Dept"),
        )
        dep_id = cur.execute("SELECT id FROM departments WHERE code = ?", (dep_code,)).fetchone()[0]
        cur.execute(
            """
            INSERT INTO students (student_id, student_name, department_id, graduation_plan, enrollment_status)
            VALUES (?, 'طالب سريان', ?, '', 'active')
            """,
            (sid, dep_id),
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS department_graduation_policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_id INTEGER NOT NULL,
                plan_code TEXT NOT NULL,
                min_total_units INTEGER NOT NULL DEFAULT 0,
                effective_from_term TEXT DEFAULT '',
                effective_from_year TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                submitted_at TEXT,
                approved_at TEXT,
                rejected_at TEXT,
                rejection_reason TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                approved_by TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # سياسة سارية أقدم
        cur.execute(
            """
            INSERT INTO department_graduation_policies
            (department_id, plan_code, min_total_units, effective_from_term, effective_from_year, status, approved_at)
            VALUES (?, '150', 150, '', '', 'approved', CURRENT_TIMESTAMP)
            """,
            (dep_id,),
        )
        # سياسة مستقبلية لا يجب أن تتفعّل الآن
        cur.execute(
            """
            INSERT INTO department_graduation_policies
            (department_id, plan_code, min_total_units, effective_from_term, effective_from_year, status, approved_at)
            VALUES (?, '155', 155, 'خريف', '2099', 'approved', CURRENT_TIMESTAMP)
            """,
            (dep_id,),
        )
        db_conn.commit()

        detected = student_graduation_plan(cur, sid)
        assert detected == "150"
