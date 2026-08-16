"""حالة الجلسة وأوضاع العمل — مستقلة عن مسارات الدخول."""
from __future__ import annotations

from flask import session

from backend.core.auth_constants import (
    SESSION_ACTIVE_MODE,
    SESSION_ADMIN_DEPARTMENT_SCOPE_ID,
    _ADMIN_SCOPE_ROLES,
)
from backend.core.auth_roles import _normalize_role


def _runtime_get_connection():
    """قراءة get_connection وقت الاستدعاء حتى تُحترم رقع الاختبار."""
    try:
        from backend.database.database import get_connection as gc

        return gc
    except Exception:  # pragma: no cover
        return None


def get_admin_department_scope_id() -> int | None:
    """معرّف القسم النشط في جلسة admin/admin_main لتصفية القوائم، أو None لكل الكلية."""
    try:
        from flask import has_request_context, session as flask_session

        if not has_request_context():
            return None
        role = _normalize_role((flask_session.get("user_role") or "").strip())
        if role not in _ADMIN_SCOPE_ROLES:
            return None
        raw = flask_session.get(SESSION_ADMIN_DEPARTMENT_SCOPE_ID)
        if raw in (None, ""):
            return None
        return int(raw)
    except (TypeError, ValueError):
        return None
    except Exception:
        return None


def resolve_admin_department_scope_api_dict() -> dict | None:
    """
    تمثيل JSON لسياق قسم المسؤول (id, code, name_ar).
    يمسح مفتاح الجلسة إن لم يعد القسم موجوداً.
    """
    raw = session.get(SESSION_ADMIN_DEPARTMENT_SCOPE_ID)
    if raw in (None, ""):
        return None
    role = _normalize_role((session.get("user_role") or "").strip())
    if role not in _ADMIN_SCOPE_ROLES:
        return None
    try:
        iid = int(raw)
    except (TypeError, ValueError):
        session.pop(SESSION_ADMIN_DEPARTMENT_SCOPE_ID, None)
        session.modified = True
        return None
    get_connection = _runtime_get_connection()
    if get_connection is None:
        return None
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT id, code, name_ar FROM departments WHERE id = ? LIMIT 1",
                (iid,),
            ).fetchone()
        if not row:
            session.pop(SESSION_ADMIN_DEPARTMENT_SCOPE_ID, None)
            session.modified = True
            return None
        if hasattr(row, "keys"):
            return {
                "id": int(row["id"]),
                "code": row["code"],
                "name_ar": row["name_ar"],
            }
        return {"id": int(row[0]), "code": row[1], "name_ar": row[2]}
    except Exception:
        import logging

        logging.getLogger(__name__).exception("resolve_admin_department_scope_api_dict failed")
        return None


def _session_has_instructor_id() -> bool:
    """هل جلسة الطلب مرتبطة بسجل instructor (للمقرراتي)؟ خارج سياق Flask يُعاد False."""
    try:
        from flask import has_request_context

        if not has_request_context():
            return False
        return bool(session.get("instructor_id"))
    except Exception:
        return False


def is_supervisor_effective_session(
    user_role: str | None,
    is_supervisor_db: int | None,
    active_mode: str | None,
) -> bool:
    """
    هل تعمل الجلسة حالياً بوصف «مشرف» (صلاحيات وواجهة الإشراف)؟
    - حساب بدور supervisor: دائماً نعم.
    - رئيس قسم: فقط عند active_mode=supervisor.
    - أستاذ + is_supervisor في قاعدة البيانات: يعتمد على active_mode (افتراضي instructor).
    """
    r = _normalize_role((user_role or "").strip())
    if r == "supervisor":
        return True
    m = (active_mode or "").strip().lower()
    if r == "head_of_department":
        return m == "supervisor"
    if r == "college_dean":
        return m == "supervisor"
    if r == "academic_vice_dean":
        return m == "supervisor"
    if r != "instructor":
        return False
    try:
        isv = int(is_supervisor_db or 0) == 1
    except (TypeError, ValueError):
        isv = False
    if not isv:
        return False
    m = (active_mode or "instructor").strip().lower()
    return m == "supervisor"


def current_supervisor_effective() -> bool:
    """نسخة مريحة تعتمد على جلسة Flask الحالية."""
    return is_supervisor_effective_session(
        session.get("user_role"),
        session.get("is_supervisor"),
        session.get(SESSION_ACTIVE_MODE),
    )


def is_instructor_portal_effective_session(
    user_role: str | None = None,
    active_mode: str | None = None,
    *,
    require_instructor_id: bool = True,
) -> bool:
    """وضع الأستاذ الفعّال: instructor، أو قيادة كلية/قسم عند active_mode=instructor."""
    role = _normalize_role((user_role or session.get("user_role") or "").strip())
    am = (
        (active_mode if active_mode is not None else session.get(SESSION_ACTIVE_MODE) or "")
        .strip()
        .lower()
    )
    try:
        db_sup = int(session.get("is_supervisor") or 0) == 1
    except (TypeError, ValueError):
        db_sup = False
    if require_instructor_id and not _session_has_instructor_id():
        return False
    if role == "instructor":
        return not db_sup or am != "supervisor"
    if role == "head_of_department":
        return am == "instructor"
    if role == "college_dean":
        return am == "instructor"
    if role == "academic_vice_dean":
        return am == "instructor"
    return False


def supervisor_portal_ui_allowed(
    user_role: str | None = None,
    active_mode: str | None = None,
) -> bool:
    """بوابة المشرف — دور supervisor أو active_mode=supervisor."""
    return is_supervisor_effective_session(
        user_role or session.get("user_role"),
        session.get("is_supervisor"),
        active_mode if active_mode is not None else session.get(SESSION_ACTIVE_MODE),
    )


def supervisor_quality_admin_blocked() -> bool:
    """مشرف في وضع الإشراف — يُمنع من صفحات إدارة ضمان الجودة."""
    return supervisor_portal_ui_allowed()


def is_college_leadership_ops_mode(
    user_role: str | None = None,
    active_mode: str | None = None,
) -> bool:
    """وضع القيادة على الكلية (عميد/وكيل) — وليس وضع الأستاذ/المشرف."""
    role = _normalize_role((user_role or session.get("user_role") or "").strip())
    am = (
        (active_mode if active_mode is not None else session.get(SESSION_ACTIVE_MODE) or "")
        .strip()
        .lower()
    )
    if role == "college_dean":
        return am in ("", "dean")
    if role == "academic_vice_dean":
        if am in ("dean", "hod", "head", "department_head"):
            am = "vice_dean"
        return am in ("", "vice_dean", "dean")
    return False


def admin_department_scope_ui_allowed(
    user_role: str | None = None,
    active_mode: str | None = None,
) -> bool:
    """شريط تصفية القسم — للإدارة وقيادة الكلية والمسجل في وضع القيادة."""
    role = _normalize_role((user_role or session.get("user_role") or "").strip())
    if role in ("admin", "admin_main", "system_admin"):
        return True
    if role == "staff":
        from backend.core.department_scope_policy import session_role_profile_scope_mode

        return session_role_profile_scope_mode() != "department"
    return is_college_leadership_ops_mode(role, active_mode)


def students_registry_view_only() -> bool:
    """
    عرض قوائم الطلبة والتسجيلات والجداول دون تعديل.
    يشمل: أستاذ/مشرف، عميد في وضع القيادة، رئيس قسم في وضع مشرف.
    """
    role = _normalize_role((session.get("user_role") or "").strip())
    if role in ("instructor", "supervisor"):
        return True
    if role == "college_dean":
        am = (session.get(SESSION_ACTIVE_MODE) or "dean").strip().lower()
        return am in ("", "dean")
    if role == "academic_vice_dean":
        am = (session.get(SESSION_ACTIVE_MODE) or "vice_dean").strip().lower()
        return am in ("", "vice_dean", "dean")
    if current_supervisor_effective() and role not in ("admin", "admin_main", "system_admin"):
        return True
    return False


def _hod_manages_college_general_scope() -> bool:
    """رئيس القسم بنطاق الاتجاه العام (GENERAL) — لإدارة المقررات المشتركة."""
    get_connection = _runtime_get_connection()
    if get_connection is None:
        return False
    try:
        from backend.core.department_scope_policy import actor_manages_college_general_scope

        uname = (session.get("user") or session.get("username") or "").strip()
        with get_connection() as conn:
            return bool(actor_manages_college_general_scope(conn, uname))
    except Exception:
        return False
