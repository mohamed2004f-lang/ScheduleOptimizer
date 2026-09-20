"""اختبارات تصنيف مراحل الجدول وعرض المحرر."""

from __future__ import annotations

from backend.core.feature_flags import is_schedule_stage_grid_enabled
from backend.core.schedule_stage_layout import (
    BUCKET_GENERAL_OR_Y1,
    BUCKET_Y3,
    BUCKET_Y4Y5,
    LAYOUT_PERSONAL_WEEKLY,
    LAYOUT_STAGE_MATRIX,
    classify_stage_bucket,
    resolve_schedule_layout_mode,
    stage_badge_for_row,
)


def test_classify_college_general_ignores_code_digit():
    assert classify_stage_bucket(course_code="GS 201", is_college_general=True) == BUCKET_GENERAL_OR_Y1
    assert classify_stage_bucket(course_code="GE 102", is_college_general=True) == BUCKET_GENERAL_OR_Y1
    assert stage_badge_for_row(course_code="GS 201", is_college_general=True) == "عام"


def test_classify_by_first_digit_of_numeric_part():
    assert classify_stage_bucket(course_code="ME 205", is_college_general=False) == BUCKET_GENERAL_OR_Y1
    assert classify_stage_bucket(course_code="ME201", is_college_general=False) == BUCKET_GENERAL_OR_Y1
    assert classify_stage_bucket(course_code="CE 210", is_college_general=False) == BUCKET_GENERAL_OR_Y1
    assert classify_stage_bucket(course_code="ME 301", is_college_general=False) == BUCKET_Y3
    assert classify_stage_bucket(course_code="ME312", is_college_general=False) == BUCKET_Y3
    assert classify_stage_bucket(course_code="ME 401", is_college_general=False) == BUCKET_Y4Y5
    assert classify_stage_bucket(course_code="ME 501", is_college_general=False) == BUCKET_Y4Y5
    assert classify_stage_bucket(course_code="ME 601", is_college_general=False) == BUCKET_Y4Y5


def test_classify_missing_code_goes_to_first_block():
    assert classify_stage_bucket(course_code="", is_college_general=False) == BUCKET_GENERAL_OR_Y1
    assert classify_stage_bucket(course_code=None, is_college_general=False) == BUCKET_GENERAL_OR_Y1
    assert stage_badge_for_row(course_code="", is_college_general=False) == "غير مصنّف"
    assert stage_badge_for_row(course_code="ME 205", is_college_general=False) == "قسم 2"


def test_stage_grid_flag_default_on(monkeypatch):
    monkeypatch.delenv("SCHEDULE_STAGE_GRID", raising=False)
    assert is_schedule_stage_grid_enabled() is True
    monkeypatch.setenv("SCHEDULE_STAGE_GRID", "0")
    assert is_schedule_stage_grid_enabled() is False
    monkeypatch.setenv("SCHEDULE_STAGE_GRID", "1")
    assert is_schedule_stage_grid_enabled() is True


def test_layout_mode_general_vs_specialty(db_conn):
    cur = db_conn.cursor()
    uid = "stg_layout"
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) "
        "VALUES ('GENERAL', 'الاتجاه العام', 'General', 1)"
    )
    gen_id = int(cur.execute("SELECT id FROM departments WHERE code='GENERAL'").fetchone()[0])
    mech_code = f"MECH_{uid}"[:12]
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (mech_code, "ميكانيكا اختبار", "Mech"),
    )
    mech_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (mech_code,)).fetchone()[0])
    pw = "x"
    try:
        row = cur.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()
        if row:
            pw = row[0]
    except Exception:
        pass
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, department_id)
        VALUES (?, ?, 'head_of_department', ?)
        """,
        (f"hod_gen_{uid}", pw, gen_id),
    )
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, department_id)
        VALUES (?, ?, 'head_of_department', ?)
        """,
        (f"hod_mech_{uid}", pw, mech_id),
    )
    db_conn.commit()

    assert resolve_schedule_layout_mode(db_conn, f"hod_gen_{uid}") == LAYOUT_PERSONAL_WEEKLY
    assert resolve_schedule_layout_mode(db_conn, f"hod_mech_{uid}") == LAYOUT_STAGE_MATRIX
    assert resolve_schedule_layout_mode(db_conn, None) == LAYOUT_PERSONAL_WEEKLY
