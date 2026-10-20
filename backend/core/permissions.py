"""
محرك الصلاحيات — كatalog، قوالب الأدوار، ودمج capabilities.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

PERMISSION_CATALOG: list[dict[str, Any]] = [
    {"key": "nav_dashboard", "group_key": "nav", "group_label_ar": "التنقل", "label_ar": "لوحة القيادة"},
    {"key": "nav_users_admin", "group_key": "users", "group_label_ar": "المستخدمون", "label_ar": "إدارة المستخدمين"},
    {"key": "can_manage_users", "group_key": "users", "group_label_ar": "المستخدمون", "label_ar": "إضافة وتعديل المستخدمين"},
    {
        "key": "can_add_department_users",
        "group_key": "users",
        "group_label_ar": "المستخدمون",
        "label_ar": "إضافة طلبة وأعضاء هيئة تدريس للقسم",
    },
    {"key": "can_view_system_accounts", "group_key": "users", "group_label_ar": "المستخدمون", "label_ar": "عرض مسؤولي النظام"},
    {"key": "can_assign_system_admin", "group_key": "users", "group_label_ar": "المستخدمون", "label_ar": "تعيين مسؤول نظام"},
    {"key": "nav_student_affairs_menu", "group_key": "students", "group_label_ar": "شؤون الطلبة", "label_ar": "قائمة شؤون الطلبة"},
    {"key": "can_manage_students", "group_key": "students", "group_label_ar": "شؤون الطلبة", "label_ar": "تعديل بيانات الطلبة"},
    {"key": "can_transfer_student_department", "group_key": "students", "group_label_ar": "شؤون الطلبة", "label_ar": "نقل/تحديد قسم الطالب"},
    {"key": "can_rename_student_id", "group_key": "students", "group_label_ar": "شؤون الطلبة", "label_ar": "تصحيح الرقم الدراسي"},
    {"key": "nav_planning_menu", "group_key": "scheduling", "group_label_ar": "الجدولة", "label_ar": "التخطيط والجدولة"},
    {"key": "nav_view_class_schedule", "group_key": "scheduling", "group_label_ar": "الجدولة", "label_ar": "عرض الجداول الدراسية"},
    {"key": "can_manage_schedule_edit", "group_key": "scheduling", "group_label_ar": "الجدولة", "label_ar": "تعديل الجداول الدراسية"},
    {"key": "nav_view_exam_schedule", "group_key": "exams", "group_label_ar": "الامتحانات", "label_ar": "عرض جداول الامتحانات"},
    {"key": "can_manage_exam_schedule_edit", "group_key": "exams", "group_label_ar": "الامتحانات", "label_ar": "تعديل جداول الامتحانات"},
    {"key": "nav_view_courses", "group_key": "courses", "group_label_ar": "المقررات", "label_ar": "عرض المقررات"},
    {"key": "can_manage_courses_edit", "group_key": "courses", "group_label_ar": "المقررات", "label_ar": "تعديل المقررات"},
    {"key": "nav_view_registrations", "group_key": "registrations", "group_label_ar": "التسجيلات", "label_ar": "عرض التسجيلات الفعلية"},
    {"key": "can_manage_registrations_edit", "group_key": "registrations", "group_label_ar": "التسجيلات", "label_ar": "تعديل التسجيلات الفعلية"},
    {"key": "nav_view_enrollment_plans", "group_key": "registrations", "group_label_ar": "التسجيلات", "label_ar": "عرض خطط التسجيل"},
    {"key": "can_manage_enrollment_plans_edit", "group_key": "registrations", "group_label_ar": "التسجيلات", "label_ar": "تعديل خطط التسجيل"},
    {"key": "can_manage_instructors_edit", "group_key": "users", "group_label_ar": "المستخدمون", "label_ar": "تعديل أعضاء هيئة التدريس"},
    {"key": "can_manage_academic_calendar_edit", "group_key": "college_ops", "group_label_ar": "تشغيل الكلّية", "label_ar": "تعديل التقويم الأكاديمي"},
    {"key": "can_manage_term_ops_college", "group_key": "college_ops", "group_label_ar": "تشغيل الكلّية", "label_ar": "تشغيل الفصل (مستوى الكلّية)"},
    {"key": "can_migrate_registrations_to_transcript", "group_key": "dangerous", "group_label_ar": "عمليات خطرة", "label_ar": "ترحيل المقررات إلى كشف الدرجات"},
    {"key": "feature_enrollment_approval_chain", "group_key": "approvals_future", "group_label_ar": "اعتمادات مستقبلية", "label_ar": "تفعيل سلسلة اعتماد خطط التسجيل"},
    {"key": "can_approve_enrollment_unit_exception", "group_key": "approvals_future", "group_label_ar": "اعتمادات مستقبلية", "label_ar": "اعتماد تجاوز حد الوحدات (وكيل/عميد)"},
    {"key": "nav_transcript_nav", "group_key": "records", "group_label_ar": "السجل الأكاديمي", "label_ar": "كشف الدرجات"},
    {"key": "can_manage_transcript_admin", "group_key": "records", "group_label_ar": "السجل الأكاديمي", "label_ar": "إدارة الكشوف"},
    {"key": "nav_grade_drafts", "group_key": "records", "group_label_ar": "السجل الأكاديمي", "label_ar": "مسودات الدرجات"},
    {"key": "nav_academic_quality_dashboard", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "لوحة الجودة"},
    {"key": "nav_department_reports", "group_key": "dept_reports", "group_label_ar": "تقارير القسم", "label_ar": "قائمة ولوحة تقارير القسم"},
    {"key": "nav_academic_reports_section", "group_key": "dept_reports", "group_label_ar": "تقارير القسم", "label_ar": "قسم تقارير القسم/الكلية (توافق قديم)"},
    {"key": "nav_performance_report", "group_key": "dept_reports", "group_label_ar": "تقارير القسم", "label_ar": "تقرير الأداء"},
    {"key": "nav_electives_report", "group_key": "dept_reports", "group_label_ar": "تقارير القسم", "label_ar": "تقرير المقررات الاختيارية"},
    {"key": "nav_registration_changes_report", "group_key": "dept_reports", "group_label_ar": "تقارير القسم", "label_ar": "تقرير الإضافة والإسقاط"},
    {"key": "nav_failed_courses_report", "group_key": "dept_reports", "group_label_ar": "تقارير القسم", "label_ar": "تقرير مقررات الرسوب"},
    {"key": "nav_not_registered_courses_report", "group_key": "dept_reports", "group_label_ar": "تقارير القسم", "label_ar": "تقرير المقررات غير المسجل بها"},
    {"key": "nav_uncompleted_courses_report", "group_key": "dept_reports", "group_label_ar": "تقارير القسم", "label_ar": "تقرير المقررات غير المنجزة"},
    {"key": "nav_prereq_registration_report", "group_key": "dept_reports", "group_label_ar": "تقارير القسم", "label_ar": "مراجعة التسجيل (أسبقية ووحدات)"},
    {"key": "nav_grade_course_mapping_audit", "group_key": "dept_reports", "group_label_ar": "تقارير القسم", "label_ar": "تدقيق ترميز المقررات"},
    {"key": "nav_analytics_report", "group_key": "dept_reports", "group_label_ar": "تقارير القسم", "label_ar": "التحليلات الأكاديمية"},
    {"key": "nav_course_registration_report", "group_key": "dept_reports", "group_label_ar": "تقارير القسم", "label_ar": "أعداد التسجيل بالمقررات"},
    {"key": "nav_college_archive", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "أرشيف الكلية"},
    {"key": "nav_surveys_results", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "نتائج الاستبيانات"},
    {"key": "nav_surveys_invites", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "دعوات الاستبيانات الخارجية"},
    {"key": "can_manage_survey_invites", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "إنشاء وإدارة روابط الدعوات الخارجية"},
    {"key": "nav_term_closure", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "إغلاق الفصل الموحّد"},
    {"key": "nav_term_ops", "group_key": "scheduling", "group_label_ar": "الجدولة", "label_ar": "تشغيل الفصل"},
    {"key": "nav_term_offerings", "group_key": "scheduling", "group_label_ar": "الجدولة", "label_ar": "اعتماد عرض المقررات"},
    {"key": "nav_evaluation_survey_admin", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "إعداد الاستبيانات"},
    {"key": "can_edit_college_identity", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "تعديل هوية الكلية"},
    {"key": "can_edit_accreditation_catalog", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "تعديل كتalog الاعتماد"},
    {"key": "nav_admin_settings", "group_key": "settings", "group_label_ar": "الإعدادات", "label_ar": "الإدارة والإعدادات"},
    {"key": "nav_college_catalog", "group_key": "settings", "group_label_ar": "الإعدادات", "label_ar": "كتalog الأقسام"},
    {"key": "nav_academic_rules", "group_key": "settings", "group_label_ar": "الإعدادات", "label_ar": "لائحة الإنذارات والفصل"},
    {"key": "can_switch_department_scope", "group_key": "settings", "group_label_ar": "الإعدادات", "label_ar": "تصفية نطاق القسم"},
    {"key": "nav_supervision", "group_key": "nav", "group_label_ar": "التنقل", "label_ar": "إسناد الطلبة للمشرفين"},
    {"key": "nav_staff_operations_menu", "group_key": "nav", "group_label_ar": "التنقل", "label_ar": "شريط الإدارة الكامل"},
    {"key": "nav_my_assigned_courses", "group_key": "nav", "group_label_ar": "التنقل", "label_ar": "مقرراتي"},
    {"key": "nav_student_portal", "group_key": "nav", "group_label_ar": "التنقل", "label_ar": "بوابة الطالب"},
]

# قوالب seed — permission keys لكل ملف
ROLE_PROFILE_SEED: list[dict[str, Any]] = [
    {
        "code": "system_admin",
        "name_ar": "مسؤول النظام",
        "base_role": "system_admin",
        "scope_mode": "college",
        "is_system": 1,
        "default_home_path": "/dashboard",
        "permissions": [p["key"] for p in PERMISSION_CATALOG],
    },
    {
        "code": "college_dean",
        "name_ar": "عميد الكلية",
        "base_role": "college_dean",
        "scope_mode": "college",
        "is_system": 1,
        "default_home_path": "/dashboard",
        "permissions": [
            "nav_dashboard", "nav_users_admin", "can_manage_users",
            "nav_student_affairs_menu",
            "nav_planning_menu",
            "nav_transcript_nav",
            "nav_grade_drafts", "nav_academic_quality_dashboard",
            "nav_department_reports", "nav_academic_reports_section", "nav_performance_report",
            "nav_electives_report", "nav_registration_changes_report",
            "nav_failed_courses_report", "nav_not_registered_courses_report",
            "nav_uncompleted_courses_report", "nav_prereq_registration_report",
            "nav_grade_course_mapping_audit",
            "nav_analytics_report", "nav_course_registration_report",
            "nav_college_archive",
            "nav_surveys_results", "nav_surveys_invites", "can_manage_survey_invites",
            "nav_evaluation_survey_admin",
            "can_edit_college_identity", "can_edit_accreditation_catalog",
            "can_switch_department_scope",
            "can_transfer_student_department",
            "nav_view_class_schedule", "nav_view_exam_schedule", "nav_view_courses",
            "nav_view_registrations", "nav_view_enrollment_plans",
            "can_manage_academic_calendar_edit", "can_manage_term_ops_college",
            "nav_staff_operations_menu", "nav_college_catalog",
            "nav_academic_rules",
        ],
    },
    {
        "code": "academic_vice_dean",
        "name_ar": "وكيل الكلية للشؤون العلمية",
        "base_role": "academic_vice_dean",
        "scope_mode": "college",
        "is_system": 1,
        "default_home_path": "/dashboard",
        "permissions": [
            "nav_dashboard",
            "nav_student_affairs_menu",
            "nav_planning_menu",
            "nav_transcript_nav",
            "nav_grade_drafts", "nav_academic_quality_dashboard",
            "nav_department_reports", "nav_academic_reports_section", "nav_performance_report",
            "nav_electives_report", "nav_registration_changes_report",
            "nav_failed_courses_report", "nav_not_registered_courses_report",
            "nav_uncompleted_courses_report", "nav_prereq_registration_report",
            "nav_grade_course_mapping_audit",
            "nav_analytics_report", "nav_course_registration_report",
            "nav_college_archive",
            "nav_surveys_results", "nav_evaluation_survey_admin",
            "can_edit_accreditation_catalog",
            "can_switch_department_scope",
            "can_transfer_student_department",
            "nav_view_class_schedule", "nav_view_exam_schedule", "nav_view_courses",
            "nav_view_registrations", "nav_view_enrollment_plans",
            "can_manage_academic_calendar_edit", "can_manage_term_ops_college",
            "nav_staff_operations_menu",
        ],
    },
    {
        "code": "college_registrar",
        "name_ar": "مسجل الكلية",
        "base_role": "staff",
        "scope_mode": "college",
        "permissions": [
            "nav_dashboard", "nav_student_affairs_menu", "can_manage_students",
            "nav_transcript_nav", "can_manage_transcript_admin", "nav_planning_menu",
            "nav_department_reports", "nav_academic_reports_section", "nav_performance_report",
            "nav_electives_report", "nav_registration_changes_report",
            "nav_failed_courses_report", "nav_not_registered_courses_report",
            "nav_uncompleted_courses_report", "nav_prereq_registration_report",
            "nav_grade_course_mapping_audit",
            "nav_analytics_report", "nav_course_registration_report",
            "can_switch_department_scope",
        ],
    },
    {
        "code": "student_affairs_officer",
        "name_ar": "موظف شؤون الطلبة",
        "base_role": "staff",
        "scope_mode": "department",
        "permissions": [
            "nav_dashboard", "nav_student_affairs_menu", "can_manage_students",
            "nav_department_reports", "nav_academic_reports_section", "nav_performance_report",
            "nav_registration_changes_report", "nav_failed_courses_report",
            "nav_not_registered_courses_report", "nav_uncompleted_courses_report",
            "nav_prereq_registration_report",
            "nav_course_registration_report",
        ],
    },
    {
        "code": "library_manager",
        "name_ar": "مدير المكتبة",
        "base_role": "staff",
        "scope_mode": "college",
        "permissions": ["nav_dashboard", "nav_student_affairs_menu"],
    },
    {
        "code": "college_quality_head",
        "name_ar": "رئيس ضمان الجودة",
        "base_role": "staff",
        "scope_mode": "college",
        "permissions": [
            "nav_academic_quality_dashboard", "nav_surveys_results",
            "nav_evaluation_survey_admin", "can_edit_accreditation_catalog",
            "nav_dashboard",
        ],
    },
    {
        "code": "dept_quality_coordinator",
        "name_ar": "منسق جودة القسم",
        "base_role": "staff",
        "scope_mode": "department",
        "permissions": [
            "nav_academic_quality_dashboard", "nav_surveys_results", "nav_dashboard",
        ],
    },
    {
        "code": "head_of_department",
        "name_ar": "رئيس قسم",
        "base_role": "head_of_department",
        "scope_mode": "department",
        "permissions": [
            "nav_dashboard", "nav_student_affairs_menu", "nav_planning_menu",
            "can_manage_schedule_edit", "nav_staff_operations_menu",
            "nav_academic_quality_dashboard", "nav_surveys_results", "nav_grade_drafts",
            "nav_supervision",
            "nav_department_reports", "nav_academic_reports_section", "nav_performance_report",
            "nav_electives_report", "nav_registration_changes_report",
            "nav_failed_courses_report", "nav_not_registered_courses_report",
            "nav_uncompleted_courses_report", "nav_prereq_registration_report",
            "nav_grade_course_mapping_audit",
            "nav_analytics_report", "nav_course_registration_report",
        ],
    },
    {
        "code": "instructor",
        "name_ar": "عضو هيئة تدريس",
        "base_role": "instructor",
        "scope_mode": "none",
        "permissions": ["nav_my_assigned_courses"],
    },
    {
        "code": "academic_supervisor",
        "name_ar": "مشرف أكاديمي",
        "base_role": "instructor",
        "scope_mode": "none",
        "permissions": ["nav_my_assigned_courses", "nav_transcript_nav"],
    },
    {
        "code": "student",
        "name_ar": "طالب",
        "base_role": "student",
        "scope_mode": "none",
        "permissions": ["nav_student_portal"],
    },
]

_PROFILE_BY_CODE = {p["code"]: p for p in ROLE_PROFILE_SEED}

CAN_ADD_DEPARTMENT_USERS = "can_add_department_users"
# مفاتيح يمكن منحها/سحبها من لوحة الأدمن الرئيسي (تجاوز مستخدم)
GRANTABLE_USER_OVERRIDE_KEYS = frozenset({
    CAN_ADD_DEPARTMENT_USERS,
    "nav_users_admin",
    "can_manage_users",
    "can_manage_schedule_edit",
    "can_manage_exam_schedule_edit",
    "can_manage_courses_edit",
    "can_manage_students",
    "can_manage_registrations_edit",
    "can_manage_enrollment_plans_edit",
    "can_manage_transcript_admin",
    "can_manage_instructors_edit",
    "can_manage_academic_calendar_edit",
    "can_manage_term_ops_college",
    "can_migrate_registrations_to_transcript",
    "feature_enrollment_approval_chain",
    "can_approve_enrollment_unit_exception",
    "can_transfer_student_department",
    "can_rename_student_id",
    "nav_student_affairs_menu",
    "nav_planning_menu",
    "nav_view_class_schedule",
    "nav_view_exam_schedule",
    "nav_view_courses",
    "nav_view_registrations",
    "nav_view_enrollment_plans",
    "nav_term_ops",
    "nav_term_offerings",
})


def role_profiles_enabled() -> bool:
    return (os.environ.get("ENABLE_ROLE_PROFILES") or "1").strip().lower() not in ("0", "false", "no")


def list_role_profiles_for_ui(*, include_system_admin: bool = False) -> list[dict]:
    out = []
    for p in ROLE_PROFILE_SEED:
        if p.get("is_system") and p["code"] == "system_admin" and not include_system_admin:
            continue
        out.append({
            "code": p["code"],
            "name_ar": p["name_ar"],
            "base_role": p["base_role"],
            "scope_mode": p.get("scope_mode", "none"),
        })
    return out


def get_profile_by_code(code: str | None) -> dict | None:
    if not code:
        return None
    return _PROFILE_BY_CODE.get((code or "").strip())


def get_profile_by_id(conn, profile_id: int | None) -> dict | None:
    if profile_id is None:
        return None
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, code, name_ar, base_role, scope_mode, is_system, default_home_path "
            "FROM role_profiles WHERE id = ?",
            (int(profile_id),),
        ).fetchone()
        if not row:
            return None
        if hasattr(row, "keys"):
            return dict(row)
        return {
            "id": row[0], "code": row[1], "name_ar": row[2], "base_role": row[3],
            "scope_mode": row[4], "is_system": row[5], "default_home_path": row[6],
        }
    except Exception:
        return _PROFILE_BY_CODE.get(str(profile_id))


def load_profile_permission_keys(conn, profile_id: int | None, profile_code: str | None = None) -> set[str]:
    """
    مفاتيح القالب الممنوحة.
    مع وجود اتصال DB: يُفضَّل المخزّن في role_profile_permissions (لا تُرجع seed وتتجاهل القاعدة).
    """
    seed = get_profile_by_code(profile_code) if profile_code else None
    if conn is None:
        return set(seed.get("permissions") or []) if seed else set()
    try:
        cur = conn.cursor()
        pid = int(profile_id) if profile_id is not None else None
        if pid is None and profile_code:
            row = cur.execute(
                "SELECT id FROM role_profiles WHERE code = ? LIMIT 1",
                (str(profile_code).strip(),),
            ).fetchone()
            if row:
                pid = int(row[0] if not hasattr(row, "keys") else row["id"])
        if pid is not None:
            rows = cur.execute(
                "SELECT permission_key FROM role_profile_permissions WHERE profile_id = ? AND granted = 1",
                (int(pid),),
            ).fetchall()
            if rows:
                return {
                    (r[0] if not hasattr(r, "keys") else r["permission_key"])
                    for r in rows
                    if (r[0] if not hasattr(r, "keys") else r["permission_key"])
                }
    except Exception:
        logger.exception("load_profile_permission_keys failed")
    if seed:
        return set(seed.get("permissions") or [])
    return set()


def load_user_overrides(conn, username: str) -> tuple[set[str], set[str]]:
    grants: set[str] = set()
    denies: set[str] = set()
    if not username:
        return grants, denies
    try:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT permission_key, granted FROM user_permission_overrides WHERE lower(username) = lower(?)",
            (username.strip(),),
        ).fetchall()
        for r in rows:
            k = r[0] if not hasattr(r, "keys") else r["permission_key"]
            g = int(r[1] if not hasattr(r, "keys") else r["granted"])
            if g == 1:
                grants.add(k)
            else:
                denies.add(k)
    except Exception:
        pass
    return grants, denies


def user_is_granted_permission(conn, username: str, permission_key: str) -> bool:
    """منح صريح عبر تجاوز المستخدم (وليس قالب الدور)."""
    grants, denies = load_user_overrides(conn, username or "")
    if permission_key in denies:
        return False
    return permission_key in grants


def load_usernames_granted_permission(conn, permission_key: str) -> set[str]:
    """أسماء المستخدمين (lowercase) الممنوحين هذه الصلاحية عبر التجاوز."""
    out: set[str] = set()
    if not permission_key:
        return out
    try:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT username FROM user_permission_overrides
            WHERE permission_key = ? AND granted = 1
            """,
            (permission_key,),
        ).fetchall()
        for r in rows:
            un = r[0] if not hasattr(r, "keys") else r["username"]
            if un:
                out.add(str(un).strip().lower())
    except Exception:
        pass
    return out


def apply_permissions_to_caps(caps: dict, granted: set[str]) -> dict:
    """يُفعّل/يُعطّل مفاتيح capabilities حسب مجموعة الصلاحيات."""
    if not caps or caps.get("v") != 1:
        return caps
    out = dict(caps)
    all_keys = {p["key"] for p in PERMISSION_CATALOG}
    for key in all_keys:
        if key in granted:
            out[key] = True
        elif key in ("can_view_system_accounts", "can_assign_system_admin"):
            out[key] = False
    # مفاتيح nav مشتقة
    if "nav_planning_menu" in granted:
        out["nav_course_registration_report"] = out.get("nav_course_registration_report") or True
    # توافق: القسم القديم أو اللوحة الجديدة يفعّلان قائمة تقارير القسم
    if "nav_academic_reports_section" in granted or "nav_department_reports" in granted:
        out["nav_department_reports"] = True
        out["nav_academic_reports_section"] = True
        for rk in (
            "nav_performance_report",
            "nav_electives_report",
            "nav_registration_changes_report",
            "nav_failed_courses_report",
            "nav_not_registered_courses_report",
            "nav_uncompleted_courses_report",
            "nav_prereq_registration_report",
            "nav_grade_course_mapping_audit",
            "nav_analytics_report",
            "nav_course_registration_report",
        ):
            out[rk] = out.get(rk) or True
    if "can_manage_users" in granted:
        out["nav_users_admin"] = True
    if CAN_ADD_DEPARTMENT_USERS in granted:
        out[CAN_ADD_DEPARTMENT_USERS] = True
        out["nav_users_admin"] = True
    if "can_edit_college_identity" in granted:
        out["nav_college_profile"] = True
    if not granted and out.get("role_profile_code") not in (None, ""):
        for k in all_keys:
            if k.startswith("nav_") or k.startswith("can_"):
                out[k] = k in granted
    return out


def merge_capabilities_with_profile(
    base_caps: dict,
    *,
    profile_keys: set[str],
    grant_overrides: set[str],
    deny_overrides: set[str],
    profile_meta: dict | None = None,
) -> dict:
    effective = set(profile_keys) | grant_overrides
    effective -= deny_overrides
    out = apply_permissions_to_caps(base_caps, effective)
    if profile_meta:
        out["role_profile_code"] = profile_meta.get("code")
        out["role_profile_name_ar"] = profile_meta.get("name_ar")
    out["permission_grants_count"] = len(effective)
    return out


def compute_system_admin_capabilities() -> dict:
    from backend.core.auth import compute_capabilities

    caps = compute_capabilities("admin_main", 0, None)
    for p in PERMISSION_CATALOG:
        caps[p["key"]] = True
    caps["can_view_system_accounts"] = True
    caps["can_assign_system_admin"] = True
    caps["is_system_admin"] = True
    caps["nav_staff_operations_menu"] = True
    caps["can_manage_users"] = True
    return caps


TEACHING_PORTAL_ADMIN_DENY_KEYS: tuple[str, ...] = (
    "nav_admin_settings",
    "nav_users_admin",
    "can_manage_users",
    "can_add_department_users",
    "nav_staff_operations_menu",
    "nav_college_catalog",
    "nav_supervision",
    "nav_academic_rules",
    "can_switch_department_scope",
    "can_view_system_accounts",
    "can_assign_system_admin",
    "nav_evaluation_survey_admin",
    "nav_surveys_results",
)


SUPERVISOR_PORTAL_QUALITY_DENY_KEYS: tuple[str, ...] = (
    "nav_academic_quality_dashboard",
    "nav_surveys_results",
    "nav_surveys_invites",
    "can_manage_survey_invites",
    "nav_term_closure",
    "nav_term_ops",
    "nav_term_offerings",
    "nav_evaluation_survey_admin",
    "nav_college_profile",
    "nav_programs_portal",
    "nav_department_lo_dashboard",
    "nav_ilo_catalog",
    "nav_course_closure_reports",
    "nav_faculty_scorecards",
    "nav_faculty_final_dossier",
)


def apply_teaching_portal_admin_deny(caps: dict) -> dict:
    """إخفاء صلاحيات الإدارة والإعدادات في وضع الأستاذ/المشرف — دون مسح صلاحيات القيادة الأساسية."""
    for key in TEACHING_PORTAL_ADMIN_DENY_KEYS:
        caps[key] = False
    return caps


def apply_supervisor_portal_caps(caps: dict) -> dict:
    """وضع المشرف — شريط إشراف + تعبئة استبيانات فقط من ضمان الجودة."""
    caps["nav_supervisor_portal_menu"] = True
    caps["nav_supervisor_quality_fill_only"] = True
    caps["nav_supervisor_dashboard"] = True
    caps["nav_supervisor_quality_report"] = True
    caps["nav_surveys_hub"] = True
    caps["nav_dashboard"] = False
    caps["nav_staff_operations_menu"] = False
    caps["nav_admin_settings"] = False
    caps["nav_student_affairs_menu"] = False
    caps["nav_instructor_portal_menu"] = False
    caps["nav_instructor_quality_hub"] = False
    caps["nav_my_assigned_courses"] = False
    caps["can_manage_transcript_admin"] = False
    for key in SUPERVISOR_PORTAL_QUALITY_DENY_KEYS:
        caps[key] = False
    return caps


def _apply_leadership_teaching_portal_caps(
    caps: dict,
    *,
    leadership_flag: str,
    switch_profile: str,
    active_mode: str,
    has_instructor_id: bool,
    vice_dean: bool = False,
) -> dict:
    """تراكب هوية القيادة على caps وضع الأستاذ/المشرف (مثل رئيس القسم)."""
    apply_teaching_portal_admin_deny(caps)
    caps[leadership_flag] = True
    caps["can_switch_active_mode"] = True
    caps["active_mode_switch_profile"] = switch_profile
    if vice_dean:
        caps["nav_college_catalog"] = False
        caps["nav_academic_rules"] = False
        caps["nav_supervision"] = False
    am = (active_mode or "").strip().lower()
    if am == "instructor":
        if has_instructor_id:
            caps["nav_my_assigned_courses"] = True
            caps["nav_instructor_portal_menu"] = True
            caps["nav_instructor_quality_hub"] = True
        else:
            caps["nav_my_assigned_courses"] = False
            caps["nav_instructor_portal_menu"] = False
            caps["nav_instructor_quality_hub"] = False
    elif am == "supervisor":
        apply_supervisor_portal_caps(caps)
    return caps


def compute_college_dean_capabilities(
    active_mode: str | None = None,
    is_supervisor_val: int = 0,
    *,
    has_instructor_id: bool = False,
) -> dict:
    """صلاحيات عميد الكلية — وضع عميد أو أستاذ/مشرف."""
    from backend.core.auth import compute_capabilities, is_supervisor_effective_session

    am = (active_mode or "dean").strip().lower()
    try:
        isv = int(is_supervisor_val or 0) == 1
    except (TypeError, ValueError):
        isv = False

    if am in ("instructor", "supervisor"):
        caps = compute_capabilities("head_of_department", isv, am)
        return _apply_leadership_teaching_portal_caps(
            caps,
            leadership_flag="is_college_dean",
            switch_profile="dean_triple" if isv else "dean_dual",
            active_mode=am,
            has_instructor_id=has_instructor_id,
        )

    prof = _PROFILE_BY_CODE["college_dean"]
    keys = set(prof.get("permissions") or [])
    base = compute_capabilities("admin_main", 0, None)
    out = merge_capabilities_with_profile(
        base, profile_keys=keys, grant_overrides=set(), deny_overrides=set(),
        profile_meta=prof,
    )
    out["can_view_system_accounts"] = False
    out["can_assign_system_admin"] = False
    out["can_manage_users"] = True
    out["nav_users_admin"] = True
    out["nav_academic_rules"] = True
    out["nav_admin_settings"] = bool(
        out.get("nav_users_admin")
        or out.get("nav_college_catalog")
        or out.get("nav_academic_rules")
        or out.get("nav_supervision")
    )
    out["is_college_dean"] = True
    out["can_switch_active_mode"] = True
    out["active_mode_switch_profile"] = "dean_triple" if isv else "dean_dual"
    out["nav_staff_operations_menu"] = True
    out["can_transfer_student_department"] = True
    out["can_rename_student_id"] = True
    out["nav_student_affairs_menu"] = True
    out["nav_course_registration_report"] = True
    out["nav_schedule_versions"] = True
    out["nav_exam_schedule_versions"] = True
    out["nav_view_class_schedule"] = True
    out["nav_view_exam_schedule"] = True
    out["nav_view_courses"] = True
    out["nav_view_registrations"] = True
    out["nav_view_enrollment_plans"] = True
    out["nav_transcript_nav"] = True
    out["nav_grade_drafts"] = True
    out["nav_evaluation_survey_admin"] = True
    # قفل مؤقت: كتالوج الاعتماد للأدمن الرئيسي فقط
    out["can_edit_accreditation_catalog"] = False
    out["is_supervisor_effective"] = False
    out["nav_surveys_results"] = True
    out["nav_surveys_invites"] = True
    out["can_manage_survey_invites"] = True
    out["nav_college_archive"] = True
    from backend.core.capability_gates import apply_leadership_ops_defaults

    return apply_leadership_ops_defaults(out, role="college_dean")


def compute_academic_vice_dean_capabilities(
    active_mode: str | None = None,
    is_supervisor_val: int = 0,
    *,
    has_instructor_id: bool = False,
) -> dict:
    """صلاحيات وكيل الشؤون العلمية — مثل العميد دون إدارة المستخدمين والإعدادات."""
    from backend.core.auth import compute_capabilities

    am = (active_mode or "vice_dean").strip().lower()
    if am in ("dean", "hod", "head", "department_head"):
        am = "vice_dean"
    try:
        isv = int(is_supervisor_val or 0) == 1
    except (TypeError, ValueError):
        isv = False

    if am in ("instructor", "supervisor"):
        caps = compute_capabilities("head_of_department", isv, am)
        return _apply_leadership_teaching_portal_caps(
            caps,
            leadership_flag="is_academic_vice_dean",
            switch_profile="vice_dean_triple" if isv else "vice_dean_dual",
            active_mode=am,
            has_instructor_id=has_instructor_id,
            vice_dean=True,
        )

    prof = _PROFILE_BY_CODE["academic_vice_dean"]
    keys = set(prof.get("permissions") or [])
    base = compute_capabilities("admin_main", 0, None)
    out = merge_capabilities_with_profile(
        base, profile_keys=keys, grant_overrides=set(), deny_overrides=set(),
        profile_meta=prof,
    )
    out["can_view_system_accounts"] = False
    out["can_assign_system_admin"] = False
    out["nav_admin_settings"] = False
    out["nav_users_admin"] = False
    out["can_manage_users"] = False
    out["nav_college_catalog"] = False
    out["nav_academic_rules"] = False
    out["nav_supervision"] = False
    out["can_edit_college_identity"] = False
    out["is_academic_vice_dean"] = True
    out["can_switch_active_mode"] = True
    out["active_mode_switch_profile"] = "vice_dean_triple" if isv else "vice_dean_dual"
    out["nav_staff_operations_menu"] = True
    out["can_transfer_student_department"] = True
    out["can_rename_student_id"] = True
    out["nav_student_affairs_menu"] = True
    out["nav_course_registration_report"] = True
    out["nav_schedule_versions"] = True
    out["nav_exam_schedule_versions"] = True
    out["nav_view_class_schedule"] = True
    out["nav_view_exam_schedule"] = True
    out["nav_view_courses"] = True
    out["nav_view_registrations"] = True
    out["nav_view_enrollment_plans"] = True
    out["nav_transcript_nav"] = True
    out["nav_grade_drafts"] = True
    out["nav_evaluation_survey_admin"] = True
    # قفل مؤقت: كتالوج الاعتماد للأدمن الرئيسي فقط
    out["can_edit_accreditation_catalog"] = False
    out["can_switch_department_scope"] = True
    out["is_supervisor_effective"] = False
    out["nav_surveys_results"] = True
    out["nav_surveys_invites"] = False
    out["can_manage_survey_invites"] = False
    out["nav_college_archive"] = True
    from backend.core.capability_gates import apply_leadership_ops_defaults

    return apply_leadership_ops_defaults(out, role="academic_vice_dean")


def resolve_capabilities_for_user(
    *,
    role: str,
    is_supervisor_val: int,
    active_mode: str | None,
    username: str | None = None,
    role_profile_id: int | None = None,
    role_profile_code: str | None = None,
    is_system_account: int = 0,
    conn=None,
) -> dict:
    from backend.core.auth import _session_has_instructor_id, compute_capabilities

    r = (role or "").strip().lower()
    if int(is_system_account or 0) == 1 or r == "system_admin":
        return compute_system_admin_capabilities()
    if r == "college_dean":
        caps = compute_college_dean_capabilities(
            active_mode,
            is_supervisor_val,
            has_instructor_id=_session_has_instructor_id(),
        )
    elif r == "academic_vice_dean":
        caps = compute_academic_vice_dean_capabilities(
            active_mode,
            is_supervisor_val,
            has_instructor_id=_session_has_instructor_id(),
        )
    else:
        caps = compute_capabilities(role, is_supervisor_val, active_mode)

    keys: set[str] = set()
    grants: set[str] = set()
    denies: set[str] = set()
    profile = None
    if role_profiles_enabled():
        if role_profile_code:
            profile = get_profile_by_code(role_profile_code)
        elif role_profile_id and conn:
            profile = get_profile_by_id(conn, role_profile_id)

        if profile is None and r in _PROFILE_BY_CODE:
            profile = _PROFILE_BY_CODE[r.replace("college_dean", "college_dean")]

        code = (profile or {}).get("code") or role_profile_code
        pid = role_profile_id or (profile or {}).get("id")
        keys = load_profile_permission_keys(conn, pid, code)
        grants, denies = load_user_overrides(conn, username or "") if conn and username else (set(), set())

        if keys or grants or denies:
            caps = merge_capabilities_with_profile(
                caps,
                profile_keys=keys,
                grant_overrides=grants,
                deny_overrides=denies,
                profile_meta=profile,
            )

    # لا تسمح لصلاحيات البروفايل القيادية بإلغاء بوابة الأستاذ/المشرف بعد التبديل
    am = (active_mode or "").strip().lower()
    if r == "head_of_department" and am == "instructor":
        caps["nav_staff_operations_menu"] = False
        caps["nav_admin_settings"] = False
        caps["nav_users_admin"] = False
        caps["can_manage_users"] = False
        caps[CAN_ADD_DEPARTMENT_USERS] = False
        caps["is_instructor_or_supervisor_nav"] = True
        if _session_has_instructor_id():
            caps["nav_instructor_portal_menu"] = True
            caps["nav_my_assigned_courses"] = True
            caps["nav_instructor_quality_hub"] = True
    elif r == "head_of_department" and am == "supervisor":
        apply_supervisor_portal_caps(caps)
        caps["nav_users_admin"] = False
        caps["can_manage_users"] = False
        caps[CAN_ADD_DEPARTMENT_USERS] = False
        caps["is_instructor_or_supervisor_nav"] = True
    elif r in ("college_dean", "academic_vice_dean") and am == "instructor":
        caps["nav_staff_operations_menu"] = False
        caps["nav_admin_settings"] = False
        caps["is_instructor_or_supervisor_nav"] = True
        if _session_has_instructor_id():
            caps["nav_instructor_portal_menu"] = True
            caps["nav_my_assigned_courses"] = True
            caps["nav_instructor_quality_hub"] = True
    elif r in ("college_dean", "academic_vice_dean") and am == "supervisor":
        apply_supervisor_portal_caps(caps)
        caps["is_instructor_or_supervisor_nav"] = True
    elif r == "instructor" and am == "supervisor":
        apply_supervisor_portal_caps(caps)
        caps["is_instructor_or_supervisor_nav"] = True
    elif r == "instructor" and am != "supervisor":
        caps["nav_staff_operations_menu"] = False
        caps["nav_instructor_portal_menu"] = True
        caps["nav_my_assigned_courses"] = True
        caps["nav_instructor_quality_hub"] = True
        caps["is_instructor_or_supervisor_nav"] = True

    # رئيس ضمان الجودة بالكلية — نتائج فقط (بدون إدارة دعوات)
    try:
        from backend.core.auth import is_college_quality_lead_session

        if is_college_quality_lead_session():
            caps["nav_surveys_results"] = True
            caps["nav_academic_quality_dashboard"] = True
            caps["nav_college_archive"] = True
            caps["nav_surveys_invites"] = False
            caps["can_manage_survey_invites"] = False
    except Exception:
        pass

    # قفل إدارة الدعوات على العميد والأدمن الرئيسي/النظام فقط
    r_norm = r
    if r_norm not in ("admin_main", "system_admin", "college_dean"):
        caps["nav_surveys_invites"] = False
        caps["can_manage_survey_invites"] = False
    elif r_norm in ("admin_main", "system_admin", "college_dean"):
        caps["nav_surveys_invites"] = True
        caps["can_manage_survey_invites"] = True

    # قفل مؤقت: خرائط الاعتماد للأدمن الرئيسي / مسؤول النظام فقط
    # (لا تعتمد على بروفايل قد يمنح can_edit_accreditation_catalog لعميد/جودة)
    caps["can_edit_accreditation_catalog"] = r_norm in ("admin_main", "system_admin")

    # مفاتيح التشغيل الجديدة — افتراضات الأدوار التشغيلية
    if r_norm in ("admin_main", "system_admin", "admin"):
        for k in (
            "can_manage_exam_schedule_edit",
            "can_manage_registrations_edit",
            "can_manage_enrollment_plans_edit",
            "can_manage_instructors_edit",
            "can_manage_academic_calendar_edit",
            "can_manage_term_ops_college",
            "can_migrate_registrations_to_transcript",
            "nav_view_class_schedule",
            "nav_view_exam_schedule",
            "nav_view_courses",
            "nav_view_registrations",
            "nav_view_enrollment_plans",
            "can_manage_courses_edit",
            "can_manage_students",
            "can_manage_transcript_admin",
        ):
            caps[k] = True
        caps["feature_enrollment_approval_chain"] = False
        caps["can_approve_enrollment_unit_exception"] = False
    elif r_norm == "head_of_department":
        am_h = (active_mode or "").strip().lower()
        head_mode = am_h in ("", "head", "hod", "department_head")
        caps["can_manage_exam_schedule_edit"] = bool(head_mode and caps.get("can_manage_schedule_edit"))
        caps["can_manage_registrations_edit"] = bool(head_mode and caps.get("can_manage_schedule_edit"))
        caps["can_manage_enrollment_plans_edit"] = bool(head_mode and caps.get("can_manage_schedule_edit"))
        caps["can_manage_students"] = bool(head_mode)
        caps["can_manage_instructors_edit"] = bool(head_mode)
        caps["can_manage_academic_calendar_edit"] = False
        caps["can_manage_term_ops_college"] = False
        caps["can_migrate_registrations_to_transcript"] = False
        caps["nav_view_class_schedule"] = True
        caps["nav_view_exam_schedule"] = True
        caps["nav_view_courses"] = True
        caps["nav_view_registrations"] = True
        caps["nav_view_enrollment_plans"] = True
        caps["feature_enrollment_approval_chain"] = False
        caps["can_approve_enrollment_unit_exception"] = False
        if head_mode:
            caps["students_data_view_only"] = False

    # منح/رفض صريح من البروفايل أو تجاوز المستخدم على مفاتيح اللوحة
    try:
        from backend.core.capability_gates import apply_explicit_permission_overrides

        caps = apply_explicit_permission_overrides(
            caps,
            profile_keys=set(keys or ()),
            grants=set(grants or ()),
            denies=set(denies or ()),
        )
    except Exception:
        pass

    # قيادة الكلية: مفاتيح تشغيل القسم = المنح الصريح فقط (لا ترث من admin_main)
    am_lead = (active_mode or "").strip().lower()
    leadership_mode = (
        (r_norm == "college_dean" and am_lead in ("", "dean"))
        or (r_norm == "academic_vice_dean" and am_lead in ("", "vice_dean", "dean"))
    )
    if leadership_mode:
        from backend.core.capability_gates import COLLEGE_OPS_EDIT_KEYS, DEPT_OPS_EDIT_KEYS

        granted_eff = set(keys or ()) | set(grants or ())
        granted_eff -= set(denies or ())
        for k in DEPT_OPS_EDIT_KEYS:
            caps[k] = k in granted_eff
        for k in COLLEGE_OPS_EDIT_KEYS:
            caps[k] = False if k in set(denies or ()) else True
        caps["students_data_view_only"] = not bool(caps.get("can_manage_students"))
        # الترحيل خطِر: admin_main فقط (لا يُفتح بقالب القيادة)
        caps["can_migrate_registrations_to_transcript"] = False

    return caps


def catalog_grouped() -> list[dict]:
    groups: dict[str, dict] = {}
    for p in PERMISSION_CATALOG:
        gk = p["group_key"]
        if gk not in groups:
            groups[gk] = {"group_key": gk, "group_label_ar": p["group_label_ar"], "items": []}
        groups[gk]["items"].append(p)
    return list(groups.values())
