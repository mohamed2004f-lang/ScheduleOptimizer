"""سياسة إدارة المستخدمين — حماية مسؤول النظام المخفي."""

from __future__ import annotations

from typing import Any

PROTECTED_ROLES = frozenset({"system_admin"})
DEAN_PROTECTED_TARGET_ROLES = frozenset({"system_admin", "admin_main", "college_dean"})


def is_system_admin_session(session_obj) -> bool:
    try:
        if int(session_obj.get("is_system_account") or 0) == 1:
            return True
    except (TypeError, ValueError):
        pass
    role = (session_obj.get("user_role") or "").strip().lower()
    return role == "system_admin"


def is_college_dean_session(session_obj) -> bool:
    return (session_obj.get("user_role") or "").strip().lower() == "college_dean"


def can_manage_users_session(session_obj) -> bool:
    role = (session_obj.get("user_role") or "").strip().lower()
    return is_system_admin_session(session_obj) or role in (
        "college_dean",
        "admin_main",
        "head_of_department",
    )


def resolve_user_role_from_db(db_role: str | None, is_system_account: int | None = 0) -> str:
    """تحويل دور DB إلى دور الجلسة."""
    if int(is_system_account or 0) == 1:
        return "system_admin"
    r = (db_role or "").strip().lower()
    if r == "admin":
        return "admin_main"
    if r in ("system_admin", "college_dean", "academic_vice_dean"):
        return r
    from backend.core.auth import _normalize_role

    return _normalize_role(db_role or "")


def user_row_is_protected(row: Any) -> bool:
    if not row:
        return False
    try:
        if hasattr(row, "keys"):
            if int(row.get("is_system_account") or 0) == 1:
                return True
            role = (row.get("role") or "").strip().lower()
        else:
            role = (row[1] if len(row) > 1 else "").strip().lower()
            if len(row) > 7:
                if int(row[7] or 0) == 1:
                    return True
    except (TypeError, ValueError, IndexError):
        role = ""
    return role in PROTECTED_ROLES


def user_dict_is_protected(user: dict | None) -> bool:
    if not user:
        return False
    if int(user.get("is_system_account") or 0) == 1:
        return True
    return (user.get("role") or "").strip().lower() in PROTECTED_ROLES


def _target_role(user: dict | None) -> str:
    if not user:
        return ""
    return (user.get("role") or "").strip().lower()


def dean_may_not_touch_user(target_user: dict | None) -> bool:
    if not target_user:
        return False
    if user_dict_is_protected(target_user):
        return True
    return _target_role(target_user) in DEAN_PROTECTED_TARGET_ROLES


def role_assignments_forbidden_for_actor(actor_session, target_role: str | None) -> str | None:
    """رسالة خطأ إن كان تعيين الدور ممنوعاً."""
    tr = (target_role or "").strip().lower()
    if tr in PROTECTED_ROLES and not is_system_admin_session(actor_session):
        return "لا يمكن تعيين أو تعديل دور مسؤول النظام."
    if tr == "system_admin":
        return "لا يمكن تعيين دور مسؤول النظام."
    if is_college_dean_session(actor_session) and tr in DEAN_PROTECTED_TARGET_ROLES:
        return "لا يمكن للعميد تعيين أو ترقية هذا الدور."
    return None


def assert_actor_may_view_user(actor_session, target_user: dict | None) -> tuple[bool, str | None]:
    if not target_user:
        return True, None
    if user_dict_is_protected(target_user) and not is_system_admin_session(actor_session):
        return False, "المستخدم غير موجود."
    return True, None


def assert_actor_may_modify_user(
    actor_session,
    target_user: dict | None,
    *,
    new_role: str | None = None,
) -> tuple[bool, str | None]:
    err = role_assignments_forbidden_for_actor(actor_session, new_role)
    if err:
        return False, err
    if target_user and user_dict_is_protected(target_user):
        if not is_system_admin_session(actor_session):
            return False, "لا يمكن تعديل أو حذف مسؤول النظام."
    if is_college_dean_session(actor_session) and dean_may_not_touch_user(target_user):
        return False, "لا يمكن للعميد تعديل أو حذف هذا المستخدم."
    return True, None


def filter_users_for_actor(actor_session, users: list[dict]) -> list[dict]:
    if is_system_admin_session(actor_session):
        return list(users)
    return [u for u in users if not user_dict_is_protected(u)]


def assignable_roles_for_actor(actor_session) -> list[dict]:
    """أدوار/قوالب يمكن اختيارها في الواجهة."""
    from backend.core.permissions import list_role_profiles_for_ui

    profiles = list_role_profiles_for_ui(include_system_admin=is_system_admin_session(actor_session))
    if is_college_dean_session(actor_session):
        return [
            p for p in profiles
            if p.get("code") not in ("system_admin", "college_dean", "admin_main")
        ]
    return profiles
