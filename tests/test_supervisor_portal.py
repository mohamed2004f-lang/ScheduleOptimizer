"""اختبارات بوابة المشرف الأكاديمي."""

from __future__ import annotations

from backend.core.auth import compute_capabilities, supervisor_portal_ui_allowed
from backend.core.permissions import apply_supervisor_portal_caps, compute_college_dean_capabilities
from backend.services.supervisor_portal import (
    _failed_course_counts,
    build_supervisor_dashboard_context,
)


def test_supervisor_role_portal_caps():
    caps = compute_capabilities("supervisor", 0)
    assert caps.get("nav_supervisor_portal_menu") is True
    assert caps.get("nav_supervisor_quality_fill_only") is True
    assert caps.get("nav_surveys_hub") is True
    assert caps.get("nav_academic_quality_dashboard") is False
    assert caps.get("nav_surveys_results") is False
    assert caps.get("nav_admin_settings") is False
    assert caps.get("nav_supervisor_dashboard") is True


def test_hod_supervisor_mode_portal_caps():
    caps = compute_capabilities("head_of_department", 0, "supervisor")
    assert caps.get("nav_supervisor_portal_menu") is True
    assert caps.get("nav_supervisor_quality_fill_only") is True
    assert caps.get("nav_academic_quality_dashboard") is False
    assert caps.get("nav_instructor_portal_menu") is False


def test_college_dean_supervisor_mode_portal_caps():
    caps = compute_college_dean_capabilities("supervisor", 1, has_instructor_id=True)
    assert caps.get("nav_supervisor_portal_menu") is True
    assert caps.get("nav_surveys_results") is False
    assert caps.get("is_college_dean") is True


def test_apply_supervisor_portal_caps_denies_quality_admin():
    base = {"nav_academic_quality_dashboard": True, "nav_surveys_results": True}
    out = apply_supervisor_portal_caps(base)
    assert out.get("nav_academic_quality_dashboard") is False
    assert out.get("nav_supervisor_portal_menu") is True


def test_supervisor_portal_ui_allowed_for_supervisor_role(app):
    with app.test_request_context():
        from flask import session
        from backend.core.auth import SESSION_ACTIVE_MODE

        session["user_role"] = "supervisor"
        session["instructor_id"] = 100
        assert supervisor_portal_ui_allowed() is True


def test_supervisor_dashboard_context_empty_students(db_conn):
    ctx = build_supervisor_dashboard_context(
        db_conn,
        role="supervisor",
        session_data={"user": "sup1", "instructor_id": 99999, "is_supervisor": 1},
        active_mode="supervisor",
    )
    assert "tasks" in ctx
    assert "students" in ctx
    assert "pending_review" in ctx
    assert ctx.get("student_count") == 0


def test_failed_course_counts_uses_grades_not_registrations(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO student_supervisor (student_id, instructor_id) VALUES ('S002', 1)"
    )
    db_conn.commit()
    counts = _failed_course_counts(db_conn, ["S001", "S002"])
    assert counts.get("S002") == 1
    assert counts.get("S001", 0) == 0


def test_supervisor_dashboard_includes_students_and_academic_fields(db_conn):
    cur = db_conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS enrollment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            status TEXT NOT NULL,
            rejection_reason TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS enrollment_plan_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            course_name TEXT NOT NULL
        );
        INSERT OR IGNORE INTO student_supervisor (student_id, instructor_id) VALUES ('S001', 1);
        INSERT OR IGNORE INTO student_supervisor (student_id, instructor_id) VALUES ('S002', 1);
        INSERT INTO enrollment_plans (id, student_id, semester, status, created_at, updated_at)
        VALUES (10, 'S001', 'ربيع 25-26', 'Pending', '2026-01-01', '2026-01-02');
        INSERT INTO enrollment_plan_items (plan_id, course_name) VALUES (10, 'رياضيات 1');
        INSERT INTO enrollment_plan_items (plan_id, course_name) VALUES (10, 'فيزياء 1');
        INSERT INTO registration_requests
            (student_id, term, course_name, action, status, requested_by, created_at, updated_at)
        VALUES ('S002', 'ربيع 25-26', 'كيمياء 1', 'add', 'pending', 'S002', '2026-01-01', '2026-01-01');
        """
    )
    db_conn.commit()
    ctx = build_supervisor_dashboard_context(
        db_conn,
        role="supervisor",
        session_data={"user": "inst1", "instructor_id": 1, "is_supervisor": 1},
        active_mode="supervisor",
        semester="ربيع 25-26",
    )
    assert ctx.get("student_count") == 2
    assert ctx.get("pending_review_count") == 2
    by_sid = {s["student_id"]: s for s in ctx.get("students") or []}
    assert by_sid["S001"]["plan_status"] == "Pending"
    assert by_sid["S001"]["plan_courses_count"] == 2
    kinds = {p["kind"] for p in ctx.get("pending_review") or []}
    assert kinds == {"enrollment_plan", "registration_request"}
