"""اختبارات تقييم المخرجات المرتبط بالدرجات."""

import pytest

from backend.core.outcome_assessment_schema import ensure_outcome_assessment_schema
from backend.core.plo_schema import ensure_plo_enhancement_schema
from backend.services.outcome_assessment import (
    list_clos_for_program_course,
    recompute_clo_mastery,
    save_assessment_items,
    save_student_scores,
)


@pytest.fixture
def lo_setup(db_conn):
    ensure_plo_enhancement_schema(db_conn)
    ensure_outcome_assessment_schema(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (id, code, name_ar) VALUES (1, 'ME', 'هندسة')"
    )
    cur.execute(
        "INSERT OR IGNORE INTO course_master (id, title_ar) VALUES (1, 'ميكانيك 101')"
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO programs (id, department_id, code, name_ar, is_active)
        VALUES (1, 1, 'ME', 'ميكانيك', 1)
        """
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO program_courses
            (id, program_id, course_master_id, course_code, is_active)
        VALUES (10, 1, 1, 'ME101', 1)
        """
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO course_learning_outcomes
            (program_course_id, code, title_ar, sort_order, is_active)
        VALUES (10, 'CLO1', 'مخرج 1', 1, 1)
        """
    )
    row = cur.execute(
        "SELECT id FROM course_learning_outcomes WHERE program_course_id=10 AND code='CLO1'"
    ).fetchone()
    clo_id = int(row[0])
    cur.execute(
        """
        INSERT OR IGNORE INTO schedule (id, course_name, program_course_id, semester, instructor_id)
        VALUES (5, 'ميكانيك 101', 10, 'خريف 2025', 1)
        """
    )
    db_conn.commit()
    return {"clo_id": clo_id, "section_id": 5, "semester": "خريف 2025"}


def test_assessment_items_and_mastery(db_conn, lo_setup):
    cur = db_conn.cursor()
    clos = list_clos_for_program_course(cur, 10)
    assert len(clos) >= 1
    item_ids = save_assessment_items(
        cur,
        lo_setup["section_id"],
        lo_setup["semester"],
        [{
            "clo_id": lo_setup["clo_id"],
            "label": "سؤال 1",
            "assessment_type": "midterm",
            "max_score": 10,
            "weight_percent": 100,
        }],
    )
    assert len(item_ids) == 1
    save_student_scores(cur, [{
        "assessment_item_id": item_ids[0],
        "student_id": "S001",
        "score": 8,
    }])
    db_conn.commit()
    n = recompute_clo_mastery(cur, lo_setup["section_id"], lo_setup["semester"])
    db_conn.commit()
    assert n >= 1
    row = cur.execute(
        """
        SELECT mastery_percent FROM student_clo_mastery
        WHERE student_id='S001' AND section_id=5 AND clo_id=?
        """,
        (lo_setup["clo_id"],),
    ).fetchone()
    assert row is not None
    assert float(row[0]) == 80.0


def test_draft_outcome_api_not_found(auth_client):
    r = auth_client.get("/grades/drafts/999999/outcome-assessment")
    assert r.status_code == 404


def test_department_dashboard_api(auth_client):
    r = auth_client.get("/academic_quality/ilo/api/department/outcomes-dashboard")
    assert r.status_code in (200, 400, 403)
    if r.status_code == 200:
        body = r.get_json() or {}
        assert body.get("status") == "ok"
        assert "glo_achievement" in body
