"""بوابات صلاحيات التشغيل — فحص can_* على مسارات الكتابة."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from flask import jsonify, request, session

# مفاتيح تعديل تشغيلية على مستوى القسم (افتراض OFF للعميد/الوكيل)
DEPT_OPS_EDIT_KEYS: tuple[str, ...] = (
    "can_manage_schedule_edit",
    "can_manage_exam_schedule_edit",
    "can_manage_courses_edit",
    "can_manage_students",
    "can_manage_registrations_edit",
    "can_manage_enrollment_plans_edit",
    "can_manage_transcript_admin",
    "can_manage_instructors_edit",
    "can_migrate_registrations_to_transcript",
)

# صلاحيات كلية موحّدة (افتراض ON للعميد/الوكيل)
COLLEGE_OPS_EDIT_KEYS: tuple[str, ...] = (
    "can_manage_academic_calendar_edit",
    "can_manage_term_ops_college",
)

# عمليات خطرة — افتراض admin_main فقط
DANGEROUS_OPS_KEYS: tuple[str, ...] = (
    "can_migrate_registrations_to_transcript",
)

# سلسلة اعتماد مستقبلية — مطفأة افتراضياً
FUTURE_APPROVAL_KEYS: tuple[str, ...] = (
    "feature_enrollment_approval_chain",
    "can_approve_enrollment_unit_exception",
)


def _normalize_role(role: str | None) -> str:
    from backend.core.auth_roles import _normalize_role as _nr

    return _nr((role or "").strip())


def resolve_request_capabilities() -> dict[str, Any]:
    """حساب قدرات الجلسة الحالية (مع تجاوزات المستخدم إن وُجدت)."""
    from backend.core.auth_session import SESSION_ACTIVE_MODE
    from backend.core.permissions import resolve_capabilities_for_user
    from backend.services.utilities import get_connection

    role = _normalize_role(session.get("user_role"))
    try:
        isv = int(session.get("is_supervisor") or 0)
    except (TypeError, ValueError):
        isv = 0
    am = session.get(SESSION_ACTIVE_MODE)
    uname = (session.get("user") or session.get("username") or "").strip()
    rp_id = session.get("role_profile_id")
    rp_code = session.get("role_profile_code")
    try:
        is_sys = int(session.get("is_system_account") or 0)
    except (TypeError, ValueError):
        is_sys = 1 if role == "system_admin" else 0

    try:
        with get_connection() as conn:
            return resolve_capabilities_for_user(
                role=role,
                is_supervisor_val=isv,
                active_mode=am,
                username=uname or None,
                role_profile_id=int(rp_id) if rp_id not in (None, "") else None,
                role_profile_code=(str(rp_code).strip() if rp_code else None),
                is_system_account=is_sys,
                conn=conn,
            )
    except Exception:
        return resolve_capabilities_for_user(
            role=role,
            is_supervisor_val=isv,
            active_mode=am,
            username=uname or None,
            role_profile_id=None,
            role_profile_code=None,
            is_system_account=is_sys,
            conn=None,
        )


def session_has_capability(key: str) -> bool:
    """هل الجلسة الحالية تملك المفتاح؟"""
    if not key:
        return False
    role = _normalize_role(session.get("user_role"))
    if role in ("admin_main", "system_admin", "admin"):
        # الأدمن الرئيسي يملك كل شيء عدا ما يُنكر صراحة لاحقاً عبر deny
        caps = resolve_request_capabilities()
        if key in caps and caps.get(key) is False:
            return False
        return True
    caps = resolve_request_capabilities()
    return bool(caps.get(key))


def capability_forbidden(message_ar: str | None = None):
    return jsonify({
        "status": "error",
        "message": message_ar or "ليست لديك صلاحية تنفيذ هذه العملية",
        "code": "FORBIDDEN",
    }), 403


def require_capability(*keys: str, message_ar: str | None = None):
    """ديكوراتور: يتطلب واحداً على الأقل من المفاتيح إن مُرّر أكثر من مفتاح."""

    def decorator(f: Callable):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not keys:
                return f(*args, **kwargs)
            if any(session_has_capability(k) for k in keys):
                return f(*args, **kwargs)
            return capability_forbidden(message_ar)

        return wrapped

    return decorator


def apply_leadership_ops_defaults(caps: dict[str, Any], *, role: str) -> dict[str, Any]:
    """
    افتراضات قيادة الكلية (عميد/وكيل في الوضع القيادي):
    تعديل أقسام = OFF، تقويم/تشغيل فصل كلّي = ON، ترحيل خطِر = OFF.
    تُستدعى قبل دمج المنح/الرفض الصريح.
    """
    out = dict(caps or {})
    r = _normalize_role(role)
    if r not in ("college_dean", "academic_vice_dean"):
        return out
    for k in DEPT_OPS_EDIT_KEYS:
        out[k] = False
    for k in COLLEGE_OPS_EDIT_KEYS:
        out[k] = True
    for k in FUTURE_APPROVAL_KEYS:
        out[k] = False
    out["students_data_view_only"] = True
    out["can_migrate_registrations_to_transcript"] = False
    return out


def apply_explicit_permission_overrides(
    caps: dict[str, Any],
    *,
    profile_keys: set[str] | None = None,
    grants: set[str] | None = None,
    denies: set[str] | None = None,
) -> dict[str, Any]:
    """تطبيق منح/رفض صريح على مفاتيح التشغيل المُدارة من اللوحة."""
    out = dict(caps or {})
    profile_keys = set(profile_keys or ())
    grants = set(grants or ())
    denies = set(denies or ())
    managed = set(DEPT_OPS_EDIT_KEYS) | set(COLLEGE_OPS_EDIT_KEYS) | set(DANGEROUS_OPS_KEYS) | set(FUTURE_APPROVAL_KEYS)
    for k in managed:
        if k in denies:
            out[k] = False
        elif k in grants or k in profile_keys:
            out[k] = True
    if out.get("can_manage_registrations_edit") or out.get("can_manage_students"):
        out["students_data_view_only"] = False
    elif out.get("students_data_view_only") is None and not out.get("can_manage_students"):
        # لا تُلغَى عرض-فقط بسبب مفاتيح تعديل أخرى (جدول/مقررات)
        pass
    return out


# مفاتيح عرض افتراضية لقيادة الكلية (لوحة الصلاحيات)
LEADERSHIP_PANEL_VIEW_KEYS: tuple[str, ...] = (
    "nav_student_affairs_menu",
    "nav_planning_menu",
    "nav_view_class_schedule",
    "nav_view_exam_schedule",
    "nav_view_courses",
    "nav_view_registrations",
    "nav_view_enrollment_plans",
    "can_transfer_student_department",
)


def panel_effective_keys_for_profile(code: str, stored_keys: set[str] | None = None) -> set[str]:
    """
    مفاتيح اللوحة كما يراها الأدمن: المخزّن + افتراضات تشغيل القيادة.
    تصفية القسم تبقى عرضاً؛ التعديل التشغيلي للأقسام OFF ما لم يُمنَح صراحة.
    """
    stored = set(stored_keys or ())
    out = set(stored)
    c = _normalize_role(code)
    if c not in ("college_dean", "academic_vice_dean"):
        return out
    for k in COLLEGE_OPS_EDIT_KEYS:
        out.add(k)
    for k in LEADERSHIP_PANEL_VIEW_KEYS:
        out.add(k)
    for k in DEPT_OPS_EDIT_KEYS:
        if k not in stored:
            out.discard(k)
    for k in DANGEROUS_OPS_KEYS:
        if k not in stored:
            out.discard(k)
    for k in FUTURE_APPROVAL_KEYS:
        if k not in stored:
            out.discard(k)
    return out
