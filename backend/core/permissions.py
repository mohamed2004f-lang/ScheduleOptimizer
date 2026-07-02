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
    {"key": "can_view_system_accounts", "group_key": "users", "group_label_ar": "المستخدمون", "label_ar": "عرض مسؤولي النظام"},
    {"key": "can_assign_system_admin", "group_key": "users", "group_label_ar": "المستخدمون", "label_ar": "تعيين مسؤول نظام"},
    {"key": "nav_student_affairs_menu", "group_key": "students", "group_label_ar": "شؤون الطلبة", "label_ar": "قائمة شؤون الطلبة"},
    {"key": "can_manage_students", "group_key": "students", "group_label_ar": "شؤون الطلبة", "label_ar": "تعديل بيانات الطلبة"},
    {"key": "nav_planning_menu", "group_key": "scheduling", "group_label_ar": "الجدولة", "label_ar": "التخطيط والجدولة"},
    {"key": "can_manage_schedule_edit", "group_key": "scheduling", "group_label_ar": "الجدولة", "label_ar": "تعديل الجدول"},
    {"key": "nav_transcript_nav", "group_key": "records", "group_label_ar": "السجل الأكademي", "label_ar": "كشف الدرجات"},
    {"key": "can_manage_transcript_admin", "group_key": "records", "group_label_ar": "السجل الأكademي", "label_ar": "إدارة الكشوف"},
    {"key": "nav_grade_drafts", "group_key": "records", "group_label_ar": "السجل الأكademي", "label_ar": "مسودات الدرجات"},
    {"key": "nav_academic_quality_dashboard", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "لوحة الجودة"},
    {"key": "nav_surveys_results", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "نتائج الاستبيانات"},
    {"key": "nav_evaluation_survey_admin", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "إعداد الاستبيانات"},
    {"key": "can_edit_college_identity", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "تعديل هوية الكلية"},
    {"key": "can_edit_accreditation_catalog", "group_key": "quality", "group_label_ar": "ضمان الجودة", "label_ar": "تعديل كتalog الاعتماد"},
    {"key": "nav_admin_settings", "group_key": "settings", "group_label_ar": "الإعدادات", "label_ar": "الإدارة والإعدادات"},
    {"key": "nav_college_catalog", "group_key": "settings", "group_label_ar": "الإعدادات", "label_ar": "كتalog الأقسام"},
    {"key": "can_switch_department_scope", "group_key": "settings", "group_label_ar": "الإعدادات", "label_ar": "تصفية نطاق القسم"},
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
            "nav_surveys_results", "nav_evaluation_survey_admin",
            "can_edit_college_identity", "can_edit_accreditation_catalog",
            "can_switch_department_scope",
            "nav_staff_operations_menu", "nav_college_catalog",
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
            "nav_surveys_results", "nav_evaluation_survey_admin",
            "can_edit_accreditation_catalog",
            "can_switch_department_scope",
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
            "can_switch_department_scope",
        ],
    },
    {
        "code": "student_affairs_officer",
        "name_ar": "موظف شؤون الطلبة",
        "base_role": "staff",
        "scope_mode": "department",
        "permissions": ["nav_dashboard", "nav_student_affairs_menu", "can_manage_students"],
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
            "nav_academic_quality_dashboard", "nav_grade_drafts",
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
    seed = get_profile_by_code(profile_code) if profile_code else None
    if profile_id is None and seed:
        return set(seed.get("permissions") or [])
    if conn is None:
        return set(seed.get("permissions") or []) if seed else set()
    try:
        cur = conn.cursor()
        if profile_id is not None:
            rows = cur.execute(
                "SELECT permission_key FROM role_profile_permissions WHERE profile_id = ? AND granted = 1",
                (int(profile_id),),
            ).fetchall()
            if rows:
                return {r[0] if not hasattr(r, "keys") else r["permission_key"] for r in rows}
        if profile_code:
            row = cur.execute("SELECT id FROM role_profiles WHERE code = ?", (profile_code,)).fetchone()
            if row:
                pid = row[0] if not hasattr(row, "keys") else row["id"]
                rows = cur.execute(
                    "SELECT permission_key FROM role_profile_permissions WHERE profile_id = ? AND granted = 1",
                    (int(pid),),
                ).fetchall()
                if rows:
                    return {r[0] if not hasattr(r, "keys") else r["permission_key"] for r in rows}
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
    if "can_manage_users" in granted:
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
    out["can_manage_students"] = False
    out["can_manage_schedule_edit"] = False
    out["can_manage_transcript_admin"] = False
    out["can_manage_courses_edit"] = False
    out["students_data_view_only"] = True
    out["nav_student_affairs_menu"] = True
    out["nav_course_registration_report"] = True
    out["nav_schedule_versions"] = True
    out["nav_exam_schedule_versions"] = True
    out["nav_transcript_nav"] = True
    out["nav_grade_drafts"] = True
    out["nav_evaluation_survey_admin"] = True
    out["can_edit_accreditation_catalog"] = True
    out["is_supervisor_effective"] = False
    return out


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
    out["can_manage_students"] = False
    out["can_manage_schedule_edit"] = False
    out["can_manage_transcript_admin"] = False
    out["can_manage_courses_edit"] = False
    out["students_data_view_only"] = True
    out["nav_student_affairs_menu"] = True
    out["nav_course_registration_report"] = True
    out["nav_schedule_versions"] = True
    out["nav_exam_schedule_versions"] = True
    out["nav_transcript_nav"] = True
    out["nav_grade_drafts"] = True
    out["nav_evaluation_survey_admin"] = True
    out["can_edit_accreditation_catalog"] = True
    out["can_switch_department_scope"] = True
    out["is_supervisor_effective"] = False
    return out


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

    if not role_profiles_enabled():
        return caps

    profile = None
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
    return caps


def catalog_grouped() -> list[dict]:
    groups: dict[str, dict] = {}
    for p in PERMISSION_CATALOG:
        gk = p["group_key"]
        if gk not in groups:
            groups[gk] = {"group_key": gk, "group_label_ar": p["group_label_ar"], "items": []}
        groups[gk]["items"].append(p)
    return list(groups.values())
