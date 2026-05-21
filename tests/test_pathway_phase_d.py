"""اختبارات المرحلة د — شبكة مستويات، Excel، دفعات الكلية."""

from backend.boot.phase0 import ensure_phase0_catalog
from backend.core.academic_pathway import (
    cohort_defaults_for_new_student,
    college_pathway_cohort_cutoff,
    normalize_pathway_stage,
    resolve_college_general_program_id,
    student_uses_college_pathway,
)
from backend.core.pathway_plan_grid import build_program_plan_grid
from backend.services.pathway_regulations import ensure_pathway_regulation_defaults
from backend.core.program_tracks import ensure_department_track_programs


def _set_cohort_year(db_conn, year: int) -> None:
    ensure_phase0_catalog(db_conn)
    cur = db_conn.cursor()
    gid = cur.execute(
        "SELECT id FROM departments WHERE code = 'GENERAL' LIMIT 1"
    ).fetchone()[0]
    ensure_pathway_regulation_defaults(db_conn)
    cur.execute(
        """
        UPDATE pathway_regulation_items
        SET value_number = ?, is_active = 1
        WHERE department_id = ? AND rule_key = 'college_pathway_cohort_from_join_year'
        """,
        (float(year), int(gid)),
    )
    db_conn.commit()


def test_build_program_plan_grid(db_conn):
    ensure_phase0_catalog(db_conn)
    ensure_department_track_programs(db_conn, "MECH", graduation_units=155)
    cur = db_conn.cursor()
    pid = cur.execute(
        "SELECT id FROM programs WHERE code = 'MECH' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    cm = cur.execute(
        "INSERT INTO course_master (title_ar, default_units) VALUES ('اختبار شبكة', 3)"
    )
    db_conn.commit()
    mid = int(cur.lastrowid)
    cur.execute(
        """
        INSERT INTO program_courses (program_id, course_master_id, course_code, level_no, requirement_scope)
        VALUES (?, ?, 'GRID01', 2, 'pre_track')
        """,
        (int(pid), mid),
    )
    db_conn.commit()
    grid = build_program_plan_grid(cur, int(pid))
    assert grid["course_count"] >= 1
    assert any(lv["level_no"] == 2 for lv in grid["levels"])


def test_cohort_defaults_and_college_pathway(db_conn):
    _set_cohort_year(db_conn, 1447)
    cur = db_conn.cursor()
    assert college_pathway_cohort_cutoff(cur, None) == 1447
    defaults = cohort_defaults_for_new_student(cur, "1447")
    assert defaults is not None
    assert defaults["pathway_stage"] == "college_general"
    prog_u1 = resolve_college_general_program_id(cur)
    assert prog_u1
    assert defaults["admission_program_id"] == prog_u1

    cur.execute(
        """
        INSERT OR REPLACE INTO students (
            student_id, student_name, join_year, pathway_stage,
            department_id, admission_program_id, current_program_id
        ) VALUES ('COHORT_D1', 'دفعة عام', '1447', 'college_general', ?, ?, ?)
        """,
        (
            defaults["department_id"],
            defaults["admission_program_id"],
            defaults["current_program_id"],
        ),
    )
    db_conn.commit()
    row = cur.execute(
        "SELECT student_id, join_year, pathway_stage, department_id, admission_program_id FROM students WHERE student_id = 'COHORT_D1'"
    ).fetchone()
    student = {
        "student_id": row[0],
        "join_year": row[1],
        "pathway_stage": row[2],
        "department_id": row[3],
        "admission_program_id": row[4],
    }
    assert student_uses_college_pathway(cur, student)
    assert normalize_pathway_stage("college_general") == "college_general"


def test_program_grid_and_plan_export_api(app, db_conn, auth_client):
    ensure_phase0_catalog(db_conn)
    pid = db_conn.cursor().execute(
        "SELECT id FROM programs WHERE code = 'MECH' LIMIT 1"
    ).fetchone()[0]
    r = auth_client.get(f"/college/catalog/program_courses/grid?program_id={pid}")
    assert r.status_code == 200
    assert (r.get_json() or {}).get("levels") is not None
    ex = auth_client.get(f"/college/catalog/program_plan/export?program_id={pid}")
    assert ex.status_code == 200
    assert "spreadsheet" in (ex.content_type or "") or "excel" in (ex.content_type or "").lower()


def test_cohort_on_add_student_via_service(db_conn):
    _set_cohort_year(db_conn, 1448)
    from backend.core.services import StudentService

    StudentService.add_student("COHORT_SVC_1", "طالب دفعة", join_year="1448")
    cur = db_conn.cursor()
    row = cur.execute(
        "SELECT pathway_stage, admission_program_id FROM students WHERE student_id = 'COHORT_SVC_1'"
    ).fetchone()
    assert row[0] == "college_general"
    assert row[1] == resolve_college_general_program_id(cur)
