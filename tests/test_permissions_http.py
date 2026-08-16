"""صلاحيات HTTP وقوالب الأدوار: طالب / أستاذ / رئيس قسم."""

from __future__ import annotations

from backend.core.auth import (
    instructor_blocked_student_portal_path,
    student_portal_path_allowed,
)
from backend.core.permissions import (
    ROLE_PROFILE_SEED,
    get_profile_by_code,
    resolve_capabilities_for_user,
)


def test_role_profile_seed_instructor_student_hod():
    codes = {p["code"] for p in ROLE_PROFILE_SEED}
    assert {"instructor", "student", "head_of_department"} <= codes
    inst = get_profile_by_code("instructor")
    assert inst is not None
    assert inst["permissions"] == ["nav_my_assigned_courses"]
    student = get_profile_by_code("student")
    assert student is not None
    assert student["permissions"] == ["nav_student_portal"]
    hod = get_profile_by_code("head_of_department")
    assert hod is not None
    assert "nav_grade_drafts" in hod["permissions"]
    assert "can_manage_schedule_edit" in hod["permissions"]
    assert "nav_student_portal" not in hod["permissions"]


def test_resolve_capabilities_instructor_student_hod(app):
    with app.app_context():
        inst = resolve_capabilities_for_user(
            role="instructor", is_supervisor_val=0, active_mode=None
        )
        assert inst.get("nav_my_assigned_courses") is True
        assert inst.get("nav_staff_operations_menu") is False
        assert not inst.get("can_manage_users")
        assert not inst.get("nav_student_portal")

        student = resolve_capabilities_for_user(
            role="student", is_supervisor_val=0, active_mode=None
        )
        assert student.get("nav_student_portal") is True
        assert not student.get("nav_grade_drafts")
        assert not student.get("can_manage_users")

        hod = resolve_capabilities_for_user(
            role="head_of_department", is_supervisor_val=0, active_mode="head"
        )
        assert hod.get("nav_grade_drafts") is True
        assert hod.get("can_manage_schedule_edit") is True
        assert not hod.get("nav_student_portal")


def test_student_portal_path_allowlist():
    assert student_portal_path_allowed("/my_portal") is True
    assert student_portal_path_allowed("/my_transcript") is True
    assert student_portal_path_allowed("/students/me") is True
    assert student_portal_path_allowed("/change_password") is True
    assert student_portal_path_allowed("/students/list") is False
    assert student_portal_path_allowed("/grades/drafts/mine") is False
    assert student_portal_path_allowed("/dashboard") is False
    assert student_portal_path_allowed("/academic_quality/api/college-archive/items") is False
    assert instructor_blocked_student_portal_path("/my_portal") is True
    assert instructor_blocked_student_portal_path("/grades/drafts/mine") is False


def test_student_json_forbidden_on_staff_routes(student_auth_client):
    headers = {"Accept": "application/json"}
    lst = student_auth_client.get("/students/list", headers=headers)
    assert lst.status_code == 403
    users = student_auth_client.get("/users/list", headers=headers)
    assert users.status_code in (403, 404)
    add = student_auth_client.post(
        "/students/add",
        json={"student_id": "HACK1", "student_name": "غير مسموح"},
        headers=headers,
    )
    assert add.status_code == 403


def test_instructor_blocked_from_student_portal(instructor_auth_client):
    resp = instructor_auth_client.get("/my_portal", follow_redirects=False)
    assert resp.status_code in (302, 301, 403)
    if resp.status_code in (302, 301):
        assert "my_courses" in resp.headers.get("Location", "")
    json_resp = instructor_auth_client.get(
        "/students/portal_summary",
        headers={"Accept": "application/json"},
    )
    assert json_resp.status_code == 403


def test_unauthenticated_json_staff_route(app):
    with app.test_client() as c:
        resp = c.get("/students/list", headers={"Accept": "application/json"})
        assert resp.status_code in (401, 302)
