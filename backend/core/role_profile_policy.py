"""سياسة إدارة قوالب الأدوار — قفل القيادة وحدود الإنشاء."""

from __future__ import annotations

import os
import re
from typing import Any, Iterable

from backend.core.user_admin_policy import is_principal_admin_session, is_system_admin_session

LOCKED_PROFILE_CODES = frozenset(
    {
        "system_admin",
        "college_dean",
        "admin_main",
        "academic_vice_dean",
    }
)

CREATABLE_BASE_ROLES = frozenset({"staff", "instructor", "head_of_department"})

_PROFILE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")

SCOPE_MODES = frozenset({"none", "college", "department"})


def role_profile_admin_enabled() -> bool:
    """علم تشغيل محرر/إنشاء القوالب (افتراضي مفعّل في غير الإنتاج إن لم يُضبط)."""
    raw = (os.environ.get("ENABLE_ROLE_PROFILE_ADMIN") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    # افتراضي: مفعّل خارج production
    env = (os.environ.get("FLASK_ENV") or "").strip().lower()
    return env != "production"


def can_manage_role_profiles(session_obj) -> bool:
    return is_principal_admin_session(session_obj)


def is_locked_profile_code(code: str | None) -> bool:
    return (code or "").strip().lower() in LOCKED_PROFILE_CODES


def assert_profile_editable(session_obj, profile: dict | None) -> tuple[bool, str | None]:
    if not can_manage_role_profiles(session_obj):
        return False, "إدارة القوالب متاحة للمسؤول الرئيسي فقط."
    if not role_profile_admin_enabled():
        return False, "محرر القوالب معطّل حالياً."
    if not profile:
        return False, "القالب غير موجود."
    code = (profile.get("code") or "").strip()
    if is_locked_profile_code(code):
        return False, "هذا القالب مقفول ولا يمكن تعديل صلاحياته من الواجهة."
    return True, None


def assert_profile_creatable(
    session_obj,
    *,
    code: str | None,
    base_role: str | None,
) -> tuple[bool, str | None]:
    if not can_manage_role_profiles(session_obj):
        return False, "إنشاء القوالب متاح للمسؤول الرئيسي فقط."
    if not role_profile_admin_enabled():
        return False, "محرر القوالب معطّل حالياً."
    c = (code or "").strip().lower()
    br = (base_role or "").strip().lower()
    if not _PROFILE_CODE_RE.match(c):
        return False, "رمز القالب غير صالح (أحرف لاتينية صغيرة وأرقام وشرطة سفلية، 3–41)."
    if is_locked_profile_code(c):
        return False, "لا يمكن إنشاء قالب بنفس رمز القوالب المقفلة."
    if br not in CREATABLE_BASE_ROLES:
        return False, "الدور الأساسي للقالب الجديد يجب أن يكون staff أو instructor أو head_of_department."
    return True, None


def sanitize_permission_keys(keys: Iterable[Any]) -> set[str]:
    from backend.core.permissions import PERMISSION_CATALOG

    allowed = {p["key"] for p in PERMISSION_CATALOG}
    out: set[str] = set()
    for k in keys or []:
        s = str(k or "").strip()
        if s in allowed:
            out.add(s)
    return out


def normalize_scope_mode(scope_mode: str | None) -> str:
    s = (scope_mode or "none").strip().lower()
    return s if s in SCOPE_MODES else "none"


def profile_flags(profile: dict | None) -> dict[str, bool]:
    code = (profile or {}).get("code") or ""
    locked = is_locked_profile_code(code)
    return {
        "locked": locked,
        "editable": not locked,
        "is_active": int((profile or {}).get("is_active") if profile and "is_active" in profile else 1) != 0,
    }
