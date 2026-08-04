"""اختبارات سجل المقررات المشتركة وتوجيه القسم المختص."""
from __future__ import annotations

import uuid

import pytest


class TestCollegeSharedCatalog:
    def test_unified_shared_visible_to_scoped_department(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES ('GENERAL', 'عام', 'Gen', 1)"
        )
        gen_id = cur.execute("SELECT id FROM departments WHERE code='GENERAL'").fetchone()[0]
        ccode = f"SC{uid}"[:12].upper()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (ccode, "مدني", "Civil"),
        )
        civil_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (ccode,)).fetchone()[0])
        ocode = f"SO{uid}"[:12].upper()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (ocode, "ميكانيك", "Mech"),
        )
        mech_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (ocode,)).fetchone()[0])
        shared_name = f"SharedU-{uid}"
        from backend.core.college_shared_catalog import save_catalog_entry

        save_catalog_entry(
            db_conn,
            {
                "catalog_key": f"su_{uid}",
                "share_type": "unified",
                "canonical_course_name": shared_name,
                "canonical_course_code": f"GS{uid[:3]}",
                "units": 3,
                "requirement_scope": "pre_track",
            },
        )
        db_conn.commit()

        from backend.core.department_scope_policy import course_in_actor_scope

        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head = f"head_sc_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head, pw, civil_id),
        )
        db_conn.commit()
        assert course_in_actor_scope(db_conn, shared_name, head)
        row = cur.execute(
            "SELECT owning_department_id FROM courses WHERE course_name=?", (shared_name,)
        ).fetchone()
        assert int(row[0]) == int(gen_id)

        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            r = c.get("/courses/list")
            names = {x.get("course_name") for x in (r.get_json() or [])}
            assert shared_name in names

    def test_responsible_department_from_schedule_not_instructor_home(self, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"HA{uid}"[:12].upper(), "منزل", "Home"),
        )
        home_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (f"HA{uid}"[:12].upper(),)).fetchone()[0])
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"TA{uid}"[:12].upper(), "تدريس", "Teach"),
        )
        teach_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (f"TA{uid}"[:12].upper(),)).fetchone()[0])
        cname = f"Route-{uid}"
        cur.execute(
            "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, ?, ?)",
            (cname, "RT101", 3, home_id),
        )
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor, semester, department_id)
            VALUES (?, 'الأحد', '08:00-10:00', '1', 'د', 'خريف 44-45', ?)
            """,
            (cname, teach_id),
        )
        db_conn.commit()
        from backend.core.department_scope_policy import resolve_course_responsible_department_id

        did = resolve_course_responsible_department_id(db_conn, cname, semester="خريف 44-45")
        assert did == teach_id
        assert did != home_id

    def test_shared_catalog_api_save_unified(self, app, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES ('GENERAL', 'عام', 'Gen', 1)"
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"AP{uid}"[:12].upper(), "مدني", "Civ"),
        )
        db_conn.commit()
        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            name = f"ApiShared-{uid}"
            r = c.post(
                "/college/catalog/shared_catalog/save",
                json={
                    "catalog_key": f"api_{uid}",
                    "share_type": "unified",
                    "canonical_course_name": name,
                    "canonical_course_code": f"GS{uid[:4]}",
                    "units": 3,
                    "requirement_scope": "pre_track",
                },
            )
            assert r.status_code == 200, r.get_data(as_text=True)
            lst = c.get("/college/catalog/shared_catalog/list")
            assert lst.status_code == 200
            keys = {x.get("canonical_course_name") for x in (lst.get_json() or {}).get("items") or []}
            assert name in keys

    def test_multi_code_per_department_units_override(self, db_conn):
        """رمز ووحدات مختلفة لكل قسم تُزامَن إلى program_courses."""
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) "
            "VALUES ('GENERAL', 'عام', 'Gen', 1)"
        )
        mcode = f"MU{uid}"[:12].upper()
        ccode = f"CU{uid}"[:12].upper()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (mcode, "ميكانيك", "Mech"),
        )
        mech_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (mcode,)).fetchone()[0])
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (ccode, "مدني", "Civ"),
        )
        civil_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (ccode,)).fetchone()[0])
        cur.execute(
            """
            INSERT INTO programs (department_id, code, name_ar, name_en, is_active)
            VALUES (?, 'PROG_MAJOR', 'رئيسي ميكانيك', 'Mech Major', 1)
            """,
            (mech_id,),
        )
        cur.execute(
            """
            INSERT INTO programs (department_id, code, name_ar, name_en, is_active)
            VALUES (?, 'PROG_MAJOR', 'رئيسي مدني', 'Civ Major', 1)
            """,
            (civil_id,),
        )
        db_conn.commit()
        from backend.core.college_shared_catalog import save_catalog_entry

        shared_name = f"SharedUnits-{uid}"
        result = save_catalog_entry(
            db_conn,
            {
                "catalog_key": f"mu_{uid}",
                "share_type": "multi_code",
                "canonical_course_name": shared_name,
                "canonical_course_code": f"SH{uid[:3]}",
                "units": 3,
                "requirement_scope": "pre_track",
                "departments": [
                    {
                        "department_id": mech_id,
                        "plan_course_code": f"ME {uid[:3]}",
                        "units_override": 3,
                    },
                    {
                        "department_id": civil_id,
                        "plan_course_code": f"CE {uid[:3]}",
                        "units_override": 4,
                    },
                ],
            },
        )
        db_conn.commit()
        entry = result["entry"]
        deps = {int(d["department_id"]): d for d in entry["departments"]}
        assert deps[mech_id]["units_override"] == 3
        assert deps[civil_id]["units_override"] == 4

        mech_pc = cur.execute(
            """
            SELECT pc.units_override, pc.course_code
            FROM program_courses pc
            INNER JOIN programs p ON p.id = pc.program_id
            WHERE p.department_id = ? AND pc.course_code = ?
            LIMIT 1
            """,
            (mech_id, f"ME {uid[:3]}"),
        ).fetchone()
        civil_pc = cur.execute(
            """
            SELECT pc.units_override, pc.course_code
            FROM program_courses pc
            INNER JOIN programs p ON p.id = pc.program_id
            WHERE p.department_id = ? AND pc.course_code = ?
            LIMIT 1
            """,
            (civil_id, f"CE {uid[:3]}"),
        ).fetchone()
        assert mech_pc is not None
        assert civil_pc is not None
        assert int(mech_pc[0] if not hasattr(mech_pc, "keys") else mech_pc["units_override"]) == 3
        assert int(civil_pc[0] if not hasattr(civil_pc, "keys") else civil_pc["units_override"]) == 4
        # المقرر التشغيلي يبقى بوحدات السجل المرجعية
        op = cur.execute(
            "SELECT units FROM courses WHERE course_name = ?", (shared_name,)
        ).fetchone()
        assert int(op[0] if not hasattr(op, "keys") else op["units"]) == 3
