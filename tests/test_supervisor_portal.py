"""اختبارات بوابة المشرف الأكاديمي."""

from __future__ import annotations

from backend.core.auth import compute_capabilities, supervisor_portal_ui_allowed
from backend.core.permissions import apply_supervisor_portal_caps, compute_college_dean_capabilities
from backend.services.supervisor_portal import build_supervisor_dashboard_context


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
    assert ctx.get("student_count") == 0
