"""قدرات الواجهة (مصدر الخادم) — منفصلة عن مسارات الدخول."""
from __future__ import annotations

from backend.core.auth_constants import _COLLEGE_LEADERSHIP_MODES
from backend.core.auth_roles import _normalize_role
from backend.core.auth_session import (
    _session_has_instructor_id,
    is_supervisor_effective_session,
)


def compute_capabilities(
    user_role: str | None,
    is_supervisor_val: int | None,
    active_mode: str | None = None,
) -> dict:
    """
    قدرات الواجهة (مصدر الخادم) — تفضّل استخدامها بدل مقارنة سلاسل الدور في JavaScript.

    تُحاكي منطق ``base_nav.html`` السابق مع إمكانية التوسعة دون تغيير كل قالب.
    """
    role = _normalize_role((user_role or "").strip())
    if role == "system_admin":
        from backend.core.permissions import compute_system_admin_capabilities
        return compute_system_admin_capabilities()
    try:
        isv = int(is_supervisor_val or 0) == 1
    except (TypeError, ValueError):
        isv = False

    am = (active_mode or "").strip().lower()
    hod_mode: str | None = None
    if role == "head_of_department":
        if am in ("", "head", "hod", "department_head"):
            hod_mode = "head"
        elif am in ("instructor", "supervisor"):
            hod_mode = am
        else:
            hod_mode = "head"

    is_supervisor_effective = is_supervisor_effective_session(role, is_supervisor_val, active_mode)

    can_switch = (role == "instructor" and isv) or (role == "head_of_department") or (role in _COLLEGE_LEADERSHIP_MODES)
    switch_profile = None
    if role == "head_of_department":
        switch_profile = "triple"
    elif role == "college_dean":
        switch_profile = "dean_triple" if isv else "dean_dual"
    elif role == "academic_vice_dean":
        switch_profile = "vice_dean_triple" if isv else "vice_dean_dual"
    elif role == "instructor" and isv:
        switch_profile = "dual"

    if hod_mode is not None:
        has_ins = _session_has_instructor_id()
        if hod_mode == "head":
            staff_planning = True
            show_grade_drafts = True
            staff_quality = True
            show_faculty_scorecards = True
            nav_my = False
            inst_sup_nav = False
            student_affairs_att_only = False
            nav_transcript = True
        elif hod_mode == "instructor":
            staff_planning = False
            show_grade_drafts = False
            staff_quality = False
            show_faculty_scorecards = True
            nav_my = has_ins
            inst_sup_nav = True
            student_affairs_att_only = True
            nav_transcript = False
        elif hod_mode == "supervisor":
            staff_planning = False
            show_grade_drafts = False
            staff_quality = False
            show_faculty_scorecards = False
            nav_my = False
            inst_sup_nav = True
            student_affairs_att_only = False
            nav_transcript = True

        hod_caps = {
            "v": 1,
            "nav_my_assigned_courses": nav_my,
            "nav_users_admin": False,
            "nav_college_catalog": False,
            "nav_college_shared_catalog": True,
            "can_manage_college_shared_catalog": False,
            "nav_supervision": False,
            "nav_academic_rules": False,
            "nav_course_registration_report": staff_planning,
            "nav_schedule_versions": staff_planning,
            "nav_exam_schedule_versions": staff_planning,
            "nav_grade_drafts": show_grade_drafts,
            "nav_course_closure_reports": staff_quality,
            "nav_faculty_scorecards": show_faculty_scorecards,
            "nav_faculty_final_dossier": staff_quality,
            "nav_academic_quality_dashboard": staff_quality,
            "nav_evaluation_survey_admin": staff_quality,
            "nav_college_profile": True,
            "nav_programs_portal": True,
            "nav_ilo_catalog": True,
            "nav_department_lo_dashboard": staff_quality,
            "nav_supervisor_quality_report": bool(is_supervisor_effective),
            "nav_supervisor_dashboard": isv and hod_mode in ("instructor", "supervisor"),
            "nav_student_course_evaluations": False,
            # رئيس القسم يظهر له hub الاستبيانات بحسب active_mode:
            # - active_mode=head/instructor => respondent_role=instructor
            # - active_mode=supervisor => respondent_role=supervisor
            "nav_surveys_hub": hod_mode in ("head", "instructor", "supervisor"),
            "nav_surveys_results": staff_quality,
            "nav_surveys_invites": False,
            "can_manage_survey_invites": False,
            "nav_term_closure": staff_quality,
            "nav_term_ops": staff_quality,
            "is_supervisor_effective": bool(is_supervisor_effective),
            "is_instructor_or_supervisor_nav": inst_sup_nav,
            "nav_staff_operations_menu": hod_mode == "head",
            "nav_instructor_portal_menu": hod_mode in ("instructor", "supervisor"),
            "nav_instructor_quality_hub": hod_mode == "instructor",
            "nav_quality_assistant": hod_mode in ("head", "instructor") or staff_quality,
            "can_switch_active_mode": can_switch,
            "active_mode_switch_profile": switch_profile,
            "is_student": False,
            "can_manage_schedule_edit": staff_planning,
            "can_manage_courses_edit": staff_planning,
            "can_manage_transcript_admin": staff_planning,
            "nav_student_affairs_attendance_only": student_affairs_att_only,
            "nav_transcript_nav": nav_transcript,
            "nav_student_affairs_menu": hod_mode == "head",
            "nav_student_portal": False,
            "nav_student_hub_more": False,
            "nav_student_registrations": False,
            "nav_student_academic_identity": False,
            "nav_student_academic_progress": False,
            "nav_dashboard": hod_mode == "head",
            "nav_admin_settings": hod_mode == "head",
            "nav_planning_student_view": False,
            "can_switch_department_scope": False,
        }
        if hod_mode == "supervisor":
            from backend.core.permissions import apply_supervisor_portal_caps
            apply_supervisor_portal_caps(hod_caps)
        return hod_caps

    staff_planning = role in ("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    # مسودات الدرجات من القائمة العلوية: الإدارة/رئيس القسم فقط؛ الأستاذ يدخلها من «مقرراتي»
    show_grade_drafts = role in ("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    staff_quality = role in ("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    dual_inst_sup = role == "instructor" and isv
    am_eff = am if am else ("instructor" if dual_inst_sup else "")
    inst_portal = role == "instructor" and (not dual_inst_sup or am_eff != "supervisor")
    sup_portal = (dual_inst_sup and am_eff == "supervisor") or role == "supervisor"
    show_faculty_scorecards = staff_quality or inst_portal
    show_ilo_catalog = staff_quality or inst_portal

    base_caps = {
        "v": 1,
        "nav_my_assigned_courses": inst_portal,
        "nav_users_admin": role in ("admin", "admin_main", "system_admin", "college_dean"),
        "nav_college_catalog": role in ("admin", "admin_main", "system_admin", "college_dean"),
        "nav_college_shared_catalog": role
        in (
            "admin",
            "admin_main",
            "system_admin",
            "college_dean",
            "academic_vice_dean",
            "head_of_department",
        ),
        "can_manage_college_shared_catalog": role
        in ("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean"),
        "nav_supervision": role in ("admin", "admin_main", "system_admin", "college_dean"),
        "nav_academic_rules": role in ("admin", "admin_main", "system_admin", "college_dean"),
        "nav_course_registration_report": staff_planning,
        "nav_schedule_versions": staff_planning,
        "nav_exam_schedule_versions": staff_planning,
        "nav_grade_drafts": show_grade_drafts,
        "nav_course_closure_reports": staff_quality,
        "nav_faculty_scorecards": show_faculty_scorecards,
        "nav_faculty_final_dossier": staff_quality,
        "nav_academic_quality_dashboard": staff_quality,
        "nav_evaluation_survey_admin": staff_quality,
        "nav_college_profile": True,
        "nav_programs_portal": True,
        "nav_ilo_catalog": show_ilo_catalog,
        "nav_department_lo_dashboard": staff_quality,
        "nav_supervisor_quality_report": bool(sup_portal),
        "nav_supervisor_dashboard": bool(sup_portal),
        "nav_student_learning_outcomes": role == "student",
        "nav_student_course_evaluations": role == "student",
        "nav_student_registrations": role == "student",
        "nav_student_portal": role == "student",
        "nav_student_hub_more": role == "student",
        "nav_student_academic_identity": role == "student",
        "nav_student_academic_progress": role == "student",
        # تظهر صفحة hub التعبئة للأدوار التي لها قوالب تعبئة:
        # طالب / أستاذ / مشرف / موظف
        "nav_surveys_hub": role in ("student", "instructor", "supervisor", "staff"),
        "nav_surveys_results": staff_quality,
        "nav_surveys_invites": role in ("admin_main", "system_admin", "college_dean"),
        "can_manage_survey_invites": role in ("admin_main", "system_admin", "college_dean"),
        "nav_term_closure": staff_quality,
        "nav_term_ops": staff_quality,
        "nav_dashboard": role != "student",
        "nav_admin_settings": role in ("admin", "admin_main", "system_admin", "college_dean"),
        "nav_student_affairs_menu": role != "student" and not sup_portal and not inst_portal,
        "nav_planning_student_view": role == "student",
        "nav_staff_operations_menu": staff_planning,
        "nav_instructor_portal_menu": inst_portal,
        "nav_instructor_quality_hub": inst_portal,
        "nav_quality_assistant": staff_quality or inst_portal,
        "is_supervisor_effective": bool(is_supervisor_effective),
        "is_instructor_or_supervisor_nav": inst_portal or sup_portal,
        "can_switch_active_mode": can_switch,
        "active_mode_switch_profile": switch_profile,
        "is_student": role == "student",
        "can_manage_schedule_edit": staff_planning and role != "student",
        "can_manage_courses_edit": staff_planning,
        "can_manage_transcript_admin": staff_planning,
        "nav_student_affairs_attendance_only": role == "instructor" and not sup_portal,
        "nav_transcript_nav": staff_planning
        or (role == "student")
        or sup_portal,
        "can_switch_department_scope": role in ("admin", "admin_main", "college_dean", "academic_vice_dean", "system_admin"),
        "can_transfer_student_department": role in ("admin", "admin_main", "college_dean", "academic_vice_dean", "system_admin"),
        "can_rename_student_id": role in ("admin", "admin_main", "college_dean", "academic_vice_dean", "system_admin"),
    }
    if role == "college_dean":
        base_caps["nav_surveys_invites"] = True
        base_caps["can_manage_survey_invites"] = True
    if sup_portal:
        from backend.core.permissions import apply_supervisor_portal_caps
        apply_supervisor_portal_caps(base_caps)
    return base_caps
