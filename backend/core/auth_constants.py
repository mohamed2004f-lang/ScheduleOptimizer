"""ثوابت جلسة المصادقة — مستقلة عن مسارات الدخول."""
from __future__ import annotations

SESSION_KEY = "authenticated"
LOGIN_PROBE_COOKIE = "_so_login_probe"
SESSION_COOKIE_NAME = "so_session"
LEGACY_AUTH_COOKIE_NAMES = ("session", "remember_token")
SESSION_USER = "user"
SESSION_LOGIN_TIME = "login_time"
# وضع العمل داخل الجلسة:
# - أستاذ + is_supervisor: instructor | supervisor
# - رئيس قسم: head | instructor | supervisor
SESSION_ACTIVE_MODE = "active_mode"
# سياق عمل المسؤول الرئيسي: تصفية بيانات حسب قسم (لا يغيّر الدور)
SESSION_ADMIN_DEPARTMENT_SCOPE_ID = "admin_department_scope_id"

_ADMIN_SCOPE_ROLES = frozenset(
    {"admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "staff"}
)
_COLLEGE_LEADERSHIP_MODES = frozenset({"college_dean", "academic_vice_dean"})
