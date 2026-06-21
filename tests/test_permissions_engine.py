"""اختبارات محرك الصلاحيات وقوالب الأدوار."""

from __future__ import annotations

from backend.core.permissions import (
    ROLE_PROFILE_SEED,
    compute_academic_vice_dean_capabilities,
    compute_college_dean_capabilities,
    compute_system_admin_capabilities,
    list_role_profiles_for_ui,
    resolve_capabilities_for_user,
)


def test_system_admin_has_full_capabilities():
    caps = compute_system_admin_capabilities()
    assert caps.get("can_view_system_accounts") is True
    assert caps.get("can_assign_system_admin") is True
    assert caps.get("nav_admin_settings") is True
    assert caps.get("can_manage_users") is True


def test_college_dean_lacks_system_admin_caps():
    caps = compute_college_dean_capabilities("dean", 0)
    assert caps.get("can_view_system_accounts") is False
    assert caps.get("can_assign_system_admin") is False
    assert caps.get("nav_admin_settings") is True
    assert caps.get("can_manage_users") is True
    assert caps.get("nav_users_admin") is True
    assert caps.get("can_manage_schedule_edit") is False
    assert caps.get("nav_grade_drafts") is True


def test_college_dean_instructor_mode_limits_admin():
    caps = compute_college_dean_capabilities("instructor", 0, has_instructor_id=True)
    assert caps.get("can_manage_users") is False
    assert caps.get("nav_admin_settings") is False
    assert caps.get("nav_staff_operations_menu") is False
    assert caps.get("nav_instructor_portal_menu") is True
    assert caps.get("nav_my_assigned_courses") is True
    assert caps.get("can_switch_department_scope") is False
    assert caps.get("nav_student_affairs_menu") is False
    assert caps.get("is_college_dean") is True


def test_college_dean_supervisor_mode_is_supervisor_portal():
    caps = compute_college_dean_capabilities("supervisor", 1, has_instructor_id=True)
    assert caps.get("nav_staff_operations_menu") is False
    assert caps.get("nav_supervisor_dashboard") is True
    assert caps.get("can_switch_department_scope") is False
    assert caps.get("is_college_dean") is True


def test_college_dean_dean_mode_view_only_students():
    caps = compute_college_dean_capabilities("dean", 0)
    assert caps.get("students_data_view_only") is True
    assert caps.get("can_manage_students") is False
    assert caps.get("can_manage_schedule_edit") is False
    assert caps.get("nav_student_affairs_menu") is True
    assert caps.get("nav_course_registration_report") is True


def test_academic_vice_dean_no_admin_settings():
    caps = compute_academic_vice_dean_capabilities("vice_dean", 0)
    assert caps.get("is_academic_vice_dean") is True
    assert caps.get("nav_admin_settings") is False
    assert caps.get("nav_users_admin") is False
    assert caps.get("can_manage_users") is False
    assert caps.get("nav_college_catalog") is False
    assert caps.get("nav_academic_rules") is False
    assert caps.get("nav_supervision") is False
    assert caps.get("can_edit_college_identity") is False
    assert caps.get("nav_grade_drafts") is True
    assert caps.get("nav_staff_operations_menu") is True
    assert caps.get("students_data_view_only") is True
    assert caps.get("can_switch_department_scope") is True


def test_academic_vice_dean_instructor_mode_limits_admin():
    caps = compute_academic_vice_dean_capabilities("instructor", 0, has_instructor_id=True)
    assert caps.get("nav_admin_settings") is False
    assert caps.get("nav_staff_operations_menu") is False
    assert caps.get("is_academic_vice_dean") is True


def test_ui_profiles_include_academic_vice_dean():
    profiles = list_role_profiles_for_ui(include_system_admin=False)
    codes = {p["code"] for p in profiles}
    assert "academic_vice_dean" in codes


def test_ui_profiles_hide_system_admin_by_default():
    profiles = list_role_profiles_for_ui(include_system_admin=False)
    codes = {p["code"] for p in profiles}
    assert "system_admin" not in codes
    assert "college_dean" in codes


def test_ui_profiles_show_system_admin_for_system_admin():
    profiles = list_role_profiles_for_ui(include_system_admin=True)
    codes = {p["code"] for p in profiles}
    assert "system_admin" in codes


def test_resolve_capabilities_system_account_flag():
    caps = resolve_capabilities_for_user(
        role="admin_main",
        is_supervisor_val=0,
        active_mode=None,
        is_system_account=1,
    )
    assert caps.get("is_system_admin") is True
    assert caps.get("can_view_system_accounts") is True


def test_role_profile_seed_count():
    assert len(ROLE_PROFILE_SEED) == 12
