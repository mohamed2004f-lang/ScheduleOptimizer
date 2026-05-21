"""اختبارات حاسبة مسار الطالب (المرحلة ج)."""

from backend.boot.phase0 import ensure_phase0_catalog
from backend.core.pathway_progress import compute_pathway_progress
from backend.core.program_tracks import ensure_department_track_programs


def test_compute_pathway_progress_missing_student(db_conn):
    cur = db_conn.cursor()
    out = compute_pathway_progress(cur, "NO_SUCH_STUDENT_XYZ")
    assert out.get("status") == "error"


def test_compute_pathway_progress_mech_student(db_conn):
    ensure_phase0_catalog(db_conn)
    ensure_department_track_programs(db_conn, "MECH", graduation_units=155)
    cur = db_conn.cursor()
    mech_dept = cur.execute("SELECT id FROM departments WHERE code = 'MECH' LIMIT 1").fetchone()
    mech_prog = cur.execute(
        "SELECT id FROM programs WHERE code = 'MECH' ORDER BY id LIMIT 1"
    ).fetchone()
    assert mech_dept and mech_prog
    dept_id = int(mech_dept[0])
    prog_id = int(mech_prog[0])
    cur.execute(
        """
        INSERT OR REPLACE INTO students (
            student_id, student_name, department_id,
            current_program_id, pathway_stage, track_code
        ) VALUES ('PP_TEST_01', 'طالب تقدم', ?, ?, 'dept_admitted', '')
        """,
        (dept_id, prog_id),
    )
    db_conn.commit()

    out = compute_pathway_progress(cur, "PP_TEST_01")
    assert out.get("status") == "ok"
    assert out.get("student_id") == "PP_TEST_01"
    assert out.get("targets", {}).get("graduation_total") == 155
    assert "by_scope" in out
    assert "totals" in out
    assert int(out["totals"]["graduation_target"]) == 155


def test_pathway_progress_api(app, db_conn):
    ensure_phase0_catalog(db_conn)
    ensure_department_track_programs(db_conn, "MECH", graduation_units=155)
    cur = db_conn.cursor()
    mech_dept = cur.execute("SELECT id FROM departments WHERE code = 'MECH' LIMIT 1").fetchone()
    mech_prog = cur.execute(
        "SELECT id FROM programs WHERE code = 'MECH' ORDER BY id LIMIT 1"
    ).fetchone()
    cur.execute(
        """
        INSERT OR REPLACE INTO students (
            student_id, student_name, department_id, current_program_id
        ) VALUES ('PP_API_01', 'API مسار', ?, ?)
        """,
        (int(mech_dept[0]), int(mech_prog[0])),
    )
    db_conn.commit()

    with app.test_client() as c:
        c.post(
            "/auth/login",
            json={"username": "admin-test", "password": "TestP@ssw0rd!"},
        )
        r = c.get("/students/pathway_progress?student_id=PP_API_01")
        assert r.status_code == 200
        body = r.get_json() or {}
        assert body.get("status") == "ok"
        assert body.get("student_id") == "PP_API_01"

        r2 = c.get("/college/catalog/student_pathway_progress?student_id=PP_API_01")
        assert r2.status_code == 200
        assert (r2.get_json() or {}).get("status") == "ok"
