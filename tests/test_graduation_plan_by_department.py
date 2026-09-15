"""اختبارات هدف تخرج القسم مقابل نظام 150/155 التراثي."""

from __future__ import annotations

import uuid

from backend.core.graduation_targets import (
    build_graduation_plan_options,
    sync_program_major_min_units,
)
from backend.services.pathway_regulations import DEPT_GRADUATION_TARGETS


def _ensure_canonical_dept(db_conn, code: str, name_ar: str) -> int:
    cur = db_conn.cursor()
    row = cur.execute(
        "SELECT id FROM departments WHERE UPPER(TRIM(code)) = ? LIMIT 1",
        (code.upper(),),
    ).fetchone()
    if row:
        return int(row[0])
    units = int(DEPT_GRADUATION_TARGETS.get(code.upper(), 155))
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (code.upper(), name_ar, code.upper()),
    )
    dept_id = int(
        cur.execute(
            "SELECT id FROM departments WHERE UPPER(TRIM(code)) = ? LIMIT 1",
            (code.upper(),),
        ).fetchone()[0]
    )
    cur.execute(
        """
        INSERT INTO programs (department_id, code, name_ar, phase, is_active, min_total_units)
        VALUES (?, 'PROG_MAJOR', ?, 'major', 1, ?)
        """,
        (dept_id, f"بكالوريوس {name_ar}", units),
    )
    db_conn.commit()
    return dept_id


def _ensure_prog_major(db_conn, dept_id: int, units: int) -> None:
    cur = db_conn.cursor()
    row = cur.execute(
        """
        SELECT id FROM programs
        WHERE department_id = ? AND UPPER(TRIM(code)) = 'PROG_MAJOR'
        LIMIT 1
        """,
        (dept_id,),
    ).fetchone()
    if row:
        cur.execute(
            "UPDATE programs SET min_total_units = ? WHERE id = ?",
            (int(units), int(row[0])),
        )
    else:
        cur.execute(
            """
            INSERT INTO programs (department_id, code, name_ar, phase, is_active, min_total_units)
            VALUES (?, 'PROG_MAJOR', 'برنامج رئيسي', 'major', 1, ?)
            """,
            (dept_id, int(units)),
        )
    db_conn.commit()


class TestGraduationPlanByDepartment:
    def test_civil_options_no_legacy_150_155(self, app, db_conn):
        dept_id = _ensure_canonical_dept(db_conn, "CIVIL", "مدني")
        opts = build_graduation_plan_options(db_conn, department_id=dept_id)
        assert opts["department_code"] == "CIVIL"
        assert opts["graduation_target_units"] == 161
        assert opts["legacy_unit_system"]["applicable"] is False
        assert opts["legacy_unit_system"]["allowed_codes"] == []
        assert "161" in (opts["label_ar"] or "")

    def test_mech_options_allow_legacy(self, app, db_conn):
        dept_id = _ensure_canonical_dept(db_conn, "MECH", "ميكانيكا")
        opts = build_graduation_plan_options(db_conn, department_id=dept_id)
        assert opts["department_code"] == "MECH"
        assert opts["graduation_target_units"] == 155
        assert opts["legacy_unit_system"]["applicable"] is True
        assert set(opts["legacy_unit_system"]["allowed_codes"]) == {"150", "155"}

    def test_admin_without_scope_needs_department(self, app, db_conn, auth_client):
        r = auth_client.get("/students/graduation_plan/options")
        assert r.status_code == 200
        body = r.get_json() or {}
        assert body.get("status") == "ok"
        assert body.get("needs_department") is True
        assert body.get("legacy_unit_system", {}).get("applicable") is False

    def test_head_civil_add_clears_legacy_plan(self, app, db_conn):
        dept_id = _ensure_canonical_dept(db_conn, "CIVIL", "مدني")
        _ensure_prog_major(db_conn, dept_id, 161)

        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        pw = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        head_user = f"head_civ_{uid}"
        cur.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (head_user, pw, dept_id),
        )
        db_conn.commit()

        sid = f"CIVADD{uid}"
        with app.test_client() as c:
            lg = c.post("/auth/login", json={"username": head_user, "password": "TestP@ssw0rd!"})
            assert lg.status_code == 200
            opts = c.get("/students/graduation_plan/options")
            assert opts.status_code == 200
            ob = opts.get_json() or {}
            assert ob.get("legacy_unit_system", {}).get("applicable") is False
            assert ob.get("graduation_target_units") == 161

            resp = c.post(
                "/students/add",
                json={
                    "student_id": sid,
                    "student_name": "طالب مدني",
                    "graduation_plan": "155",
                },
            )
            assert resp.status_code == 200, resp.get_data(as_text=True)
            body = resp.get_json() or {}
            assert body.get("status") == "ok"
            assert body.get("department_id") == int(dept_id)

        row = cur.execute(
            "SELECT department_id, COALESCE(graduation_plan,'') FROM students WHERE student_id = ?",
            (sid,),
        ).fetchone()
        assert int(row[0]) == int(dept_id)
        assert (row[1] or "").strip() == ""

    def test_sync_prog_major_min_units_civil_161(self, app, db_conn):
        dept_id = _ensure_canonical_dept(db_conn, "CIVIL", "مدني")
        _ensure_prog_major(db_conn, dept_id, 160)
        sync_program_major_min_units(db_conn)
        db_conn.commit()
        row = db_conn.execute(
            """
            SELECT min_total_units FROM programs
            WHERE department_id = ? AND UPPER(TRIM(code)) = 'PROG_MAJOR'
            LIMIT 1
            """,
            (dept_id,),
        ).fetchone()
        assert int(row[0]) == 161
