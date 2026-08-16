"""
نظام المصادقة المحسّن
يستخدم متغيرات البيئة لتخزين بيانات الدخول بشكل آمن
"""
import os
import sys
from functools import wraps
from flask import request, jsonify, session, redirect
import hashlib
import secrets
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

from backend.core.security import rate_limit

try:
    from backend.services.utilities import get_connection
except Exception:  # pragma: no cover - حماية فقط في حال مشاكل الاستيراد
    get_connection = None

# Flask-Login (ترقية تدريجية بدون كسر النظام الحالي)
try:
    from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user
except Exception:  # pragma: no cover
    LoginManager = None
    UserMixin = object
    current_user = None
    login_user = None
    logout_user = None

try:
    from werkzeug.security import generate_password_hash, check_password_hash
except Exception:  # pragma: no cover
    generate_password_hash = None
    check_password_hash = None

# استيراد الإعدادات من config.py
try:
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    from config import ADMIN_USERNAME, ADMIN_PASSWORD, SECRET_KEY, SESSION_LIFETIME_MINUTES
    # تسجيل اسم المستخدم الإداري لتحسين تتبع الأخطاء (بدون طباعة كلمة المرور)
    logger.info("Auth config loaded. ADMIN_USERNAME=%s", ADMIN_USERNAME)
except ImportError as e:
    logger.warning(f"Could not import from config.py: {e}")
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
    if not ADMIN_PASSWORD:
        raise RuntimeError(
            "\n\n"
            "===== خطأ أمان حرج =====\n"
            "ADMIN_PASSWORD غير معيَّنة في متغيرات البيئة ولم يتم استيراد config.py.\n"
            "يجب تعيين ADMIN_PASSWORD في ملف .env أو متغيرات البيئة.\n"
            "============================\n"
        )
    SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
    SESSION_LIFETIME_MINUTES = 60

# حسابات إضافية اختيارية للمشرف والطالب (يمكن ضبطها من .env)
SUPERVISOR_USERNAME = os.environ.get("SUPERVISOR_USERNAME")
SUPERVISOR_PASSWORD = os.environ.get("SUPERVISOR_PASSWORD")
STUDENT_USERNAME = os.environ.get("STUDENT_USERNAME")
STUDENT_PASSWORD = os.environ.get("STUDENT_PASSWORD")

from backend.core.auth_constants import (  # noqa: E402
    LEGACY_AUTH_COOKIE_NAMES,
    LOGIN_PROBE_COOKIE,
    SESSION_ACTIVE_MODE,
    SESSION_ADMIN_DEPARTMENT_SCOPE_ID,
    SESSION_COOKIE_NAME,
    SESSION_KEY,
    SESSION_LOGIN_TIME,
    SESSION_USER,
    _ADMIN_SCOPE_ROLES,
    _COLLEGE_LEADERSHIP_MODES,  # noqa: F401 — واجهة عامة
)
from backend.core.auth_guards import (  # noqa: E402
    instructor_blocked_student_portal_path,
    register_instructor_route_guard,
    register_student_route_guard,
    student_portal_path_allowed,
)
from backend.core.auth_password import hash_password, verify_password  # noqa: E402
from backend.core.auth_roles import _HEAD_ROLE_ALIASES, _normalize_role  # noqa: E402
from backend.core.auth_session import (  # noqa: E402, F401
    _hod_manages_college_general_scope,
    _session_has_instructor_id,
    admin_department_scope_ui_allowed,
    current_supervisor_effective,
    get_admin_department_scope_id,
    is_college_leadership_ops_mode,
    is_instructor_portal_effective_session,
    is_supervisor_effective_session,
    resolve_admin_department_scope_api_dict,
    students_registry_view_only,
    supervisor_portal_ui_allowed,
    supervisor_quality_admin_blocked,
)
from backend.core.auth_capabilities import compute_capabilities  # noqa: E402


def _fetch_user_session_row(cur, username: str):
    """قراءة صف المستخدم مع دعم قواعد بيانات قبل إضافة is_college_quality_lead."""
    from backend.repositories.users_repo import fetch_user_session_row

    return fetch_user_session_row(cur, username)


def _fetch_user_login_row(cur, username: str):
    """قراءة صف تسجيل الدخول مع دعم ترقية العمود الجديد."""
    from backend.repositories.users_repo import fetch_user_login_row

    return fetch_user_login_row(cur, username)


def _sync_user_session_from_db(username: str | None) -> None:
    """
    يزامن role و is_supervisor و instructor_id من جدول users إلى الجلسة.
    مصدر الحقيقة: قاعدة البيانات — يُصلح تعارض الجلسة مع السجل (مثلاً بعد تعديل الدور أو Flask-Login).
    """
    if get_connection is None or not (username or "").strip():
        return
    un = str(username).strip()
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            row = _fetch_user_session_row(cur, un)
        if not row:
            return
        db_role_raw = row[0]
        db_sup = row[1]
        db_student = row[2] if len(row) > 2 else None
        db_inst = row[3] if len(row) > 3 else None
        db_cq_lead = row[4] if len(row) > 4 else 0

        role_n = _normalize_role(str(db_role_raw or "").strip())
        try:
            sup_i = int(db_sup or 0)
        except (TypeError, ValueError):
            sup_i = 0
        try:
            cq_lead = int(db_cq_lead or 0)
        except (TypeError, ValueError):
            cq_lead = 0

        session["user_role"] = role_n
        session["is_supervisor"] = 1 if sup_i == 1 else 0
        session["is_college_quality_lead"] = 1 if cq_lead == 1 else 0
        session["is_platform_admin"] = 1 if str(db_role_raw or "").strip().lower() == "admin" else 0
        if db_inst is not None:
            try:
                session["instructor_id"] = int(db_inst)
            except (TypeError, ValueError):
                session.pop("instructor_id", None)
        else:
            session.pop("instructor_id", None)
        if role_n == "student" and db_student:
            session["student_id"] = str(db_student).strip()
        session.modified = True
    except Exception:
        logger.exception("sync_user_session_from_db failed username=%s", un)



def _effective_roles(user_role: str) -> set:
    """
    إرجاع مجموعة الأدوار الفعلية للمستخدم (بدون خلط غير آمن).
    - instructor + is_supervisor=1 => يُضاف supervisor فقط عند active_mode=supervisor
    - supervisor (دور في DB) => تُضاف instructor للسماح بمسارات التدريس عند الحاجة
    """
    r = _normalize_role(user_role)
    roles = {r} if r else set()
    if r == "system_admin":
        roles.update({"system_admin", "admin_main", "admin"})
    try:
        is_sup = int(session.get("is_supervisor") or 0)
    except Exception:
        is_sup = 0
    active = session.get(SESSION_ACTIVE_MODE)
    if r == "college_dean":
        roles.add("college_dean")
        am = (active or "dean").strip().lower() if active is not None else "dean"
        if am == "instructor":
            roles.add("instructor")
        elif am == "supervisor":
            roles.update({"supervisor", "instructor"})
    if r == "academic_vice_dean":
        roles.add("academic_vice_dean")
        am = (active or "vice_dean").strip().lower() if active is not None else "vice_dean"
        if am in ("dean", "hod", "head", "department_head"):
            am = "vice_dean"
        if am == "instructor":
            roles.add("instructor")
        elif am == "supervisor":
            roles.update({"supervisor", "instructor"})
    if r == "instructor" and is_sup == 1:
        if is_supervisor_effective_session(r, is_sup, active):
            roles.add("supervisor")
    if r == "supervisor":
        roles.add("instructor")
    # توحيد رئيس القسم مع المسؤول الرئيسي على مستوى الصلاحيات العامة.
    # الاستثناءات الخاصة بالإدارة/الإعدادات تُطبَّق بشكل صريح داخل role_required.
    if r == "head_of_department":
        roles.update({"admin_main", "admin"})
        active = (session.get(SESSION_ACTIVE_MODE) or "head").strip().lower()
        if active == "instructor":
            roles.add("instructor")
        elif active == "supervisor":
            roles.add("supervisor")
            roles.add("instructor")
    return roles


def _admin_settings_blocked_prefixes() -> tuple[str, ...]:
    return (
        "/users",
        "/users_admin",
        "/admin/project_status",
        "/admin/backup_page",
        "/admin/backup/",
        "/admin/backup_now",
        "/admin/system_diagnostics",
        "/admin/settings",
        "/academic_rules",
        "/academic_rules_page",
        "/college_catalog",
        "/college/catalog",
        "/department_policy_approvals",
        "/department_policy_approvals_page",
        "/course_equivalences",
        "/course_equivalences_page",
        "/system_docs",
    )


def _dual_role_admin_blocked_path(path: str, user_role: str, active_mode: str | None) -> bool:
    """مسارات الإدارة محصورة على الوضع القيادي (رئيس قسم/عميد) وليس وضع الأستاذ/المشرف."""
    r = _normalize_role((user_role or "").strip())
    am = (active_mode or "").strip().lower()
    if r == "head_of_department":
        if am in ("instructor", "supervisor"):
            p = (path or "").strip().lower()
            return any(p.startswith(prefix) for prefix in _admin_settings_blocked_prefixes())
        return False
    if r == "college_dean":
        if am in ("instructor", "supervisor"):
            p = (path or "").strip().lower()
            return any(p.startswith(prefix) for prefix in _admin_settings_blocked_prefixes())
        return False
    if r == "academic_vice_dean":
        p = (path or "").strip().lower()
        return any(p.startswith(prefix) for prefix in _admin_settings_blocked_prefixes())
    return False


def _head_of_department_blocked_path(path: str) -> bool:
    """Legacy wrapper — يستخدم active_mode من الجلسة."""
    try:
        am = session.get(SESSION_ACTIVE_MODE)
        role = session.get("user_role")
    except Exception:
        return False
    return _dual_role_admin_blocked_path(path, role or "", am)


# إعداد Flask-Login (username هو المعرّف لأن جدول users يستخدمه كمفتاح أساسي)
login_manager = LoginManager() if LoginManager is not None else None
if login_manager is not None:
    login_manager.login_view = "login_page"  # endpoint في app.py لمسار /login
    login_manager.login_message = "يجب تسجيل الدخول للوصول إلى هذه الصفحة."
    # خلف Cloudflare Tunnel قد يتغيّر IP بين الطلبات — لا تُبطل الجلسة بسبب ذلك
    login_manager.session_protection = None


class User(UserMixin):
    def __init__(self, username: str, role: str, student_id=None, instructor_id=None):
        self.id = str(username)  # Flask-Login يخزن هذا كـ user_id
        self.username = str(username)
        self.role = role
        self.student_id = student_id
        self.instructor_id = instructor_id


if login_manager is not None:
    @login_manager.user_loader
    def load_user(user_id):
        if get_connection is None:
            return None
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                row = cur.execute(
                    "SELECT username, role, student_id, instructor_id FROM users WHERE username = ?",
                    (str(user_id),),
                ).fetchone()
                if not row:
                    return None
                try:
                    return User(
                        username=row["username"] if "username" in row.keys() else row[0],
                        role=row["role"] if "role" in row.keys() else row[1],
                        student_id=row["student_id"] if "student_id" in row.keys() else (row[2] if len(row) > 2 else None),
                        instructor_id=row["instructor_id"] if "instructor_id" in row.keys() else (row[3] if len(row) > 3 else None),
                    )
                except Exception:
                    return User(
                        username=row[0],
                        role=row[1],
                        student_id=(row[2] if len(row) > 2 else None),
                        instructor_id=(row[3] if len(row) > 3 else None),
                    )
        except Exception:
            logger.exception("Error loading user (Flask-Login)")
        return None

    @login_manager.unauthorized_handler
    def _unauthorized():
        accept = (request.headers.get("Accept") or "").lower()
        is_api_request = (
            request.is_json
            or "application/json" in accept
            or request.path.startswith("/api/")
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        )
        if is_api_request:
            return jsonify({
                "status": "error",
                "message": "يجب تسجيل الدخول للوصول إلى هذه الصفحة",
                "code": "UNAUTHORIZED",
            }), 401
        return redirect("/login")



def _purge_legacy_auth_cookies(resp):
    """حذف cookies قديمة (اسم session + domain-scoped) تسبب تعارضاً خلف Cloudflare."""
    if not any(request.cookies.get(n) for n in LEGACY_AUTH_COOKIE_NAMES):
        pass  # still attempt delete below when clearing logout
    host = (request.host or "").split(":")[0].lower()
    domains = {None}
    if host.endswith("uod-engineering.org"):
        domains.update({".uod-engineering.org", "uod-engineering.org"})
    if host.startswith("www."):
        bare = host[4:]
        domains.update({f".{bare}", bare})
    for name in LEGACY_AUTH_COOKIE_NAMES:
        for domain in domains:
            if domain:
                resp.delete_cookie(name, path="/", domain=domain)
            else:
                resp.delete_cookie(name, path="/")
    return resp


def _clear_session_cookies(resp):
    """حذف cookie الجلسة الحالية (so_session) بكل النطاقات المحتملة."""
    from flask import current_app

    name = current_app.config.get("SESSION_COOKIE_NAME", SESSION_COOKIE_NAME)
    domain_cfg = (current_app.config.get("SESSION_COOKIE_DOMAIN") or "").strip() or None
    host = (request.host or "").split(":")[0].lower()
    domains = {None, domain_cfg}
    if host.endswith("uod-engineering.org"):
        domains.update({".uod-engineering.org", "uod-engineering.org"})
    if host.startswith("www."):
        bare = host[4:]
        domains.update({f".{bare}", bare})

    cookie_names = {name, "session", "remember_token"}
    for cookie_name in cookie_names:
        for domain in domains:
            try:
                if domain:
                    resp.delete_cookie(cookie_name, path="/", domain=domain)
                else:
                    resp.delete_cookie(cookie_name, path="/")
            except Exception:
                pass
    _purge_legacy_auth_cookies(resp)
    try:
        resp.delete_cookie(LOGIN_PROBE_COOKIE, path="/")
    except Exception:
        pass
    return resp


def _session_is_logged_in() -> bool:
    """مصدر الحقيقة للمصادقة — SESSION_KEY فقط (لا نُعيد الدخول عبر Flask-Login بعد الخروج)."""
    return bool(session.get(SESSION_KEY))


def perform_logout() -> None:
    """مسح جلسة المصادقة (مشترك بين POST /auth/logout و GET /logout)."""
    try:
        if logout_user is not None:
            logout_user()
    except Exception:
        logger.exception("failed to logout_user (Flask-Login)")
    try:
        session.clear()
        session.modified = True
    except Exception:
        logger.exception("failed to clear session on logout")


def _redirect_to_login():
    """توجيه لصفحة الدخول؛ إذا جاء بعد محاولة login ناجحة لكن بدون جلسة، أظهر السبب."""
    if request.args.get("logged_in") == "1" or request.cookies.get(LOGIN_PROBE_COOKIE):
        return redirect("/login?error=SESSION_NOT_SAVED")
    return redirect("/login")


def complete_login_session(login_ctx: dict, *, wants_json: bool):
    """إتمام جلسة الدخول بعد كلمة المرور (وبعد MFA إن وُجد)."""
    from flask import make_response, redirect as _redirect

    canonical_user = (login_ctx.get("canonical_user") or "").strip()
    role = login_ctx.get("role")
    student_id = login_ctx.get("student_id")
    instructor_id = login_ctx.get("instructor_id")
    is_supervisor_flag = int(login_ctx.get("is_supervisor_flag") or 0)
    is_system_account_flag = int(login_ctx.get("is_system_account_flag") or 0)
    is_dept_quality_coordinator_flag = int(login_ctx.get("is_dept_quality_coordinator_flag") or 0)
    role_profile_id_val = login_ctx.get("role_profile_id_val")
    display_title_ar_val = login_ctx.get("display_title_ar_val")
    college_quality_lead_flag = int(login_ctx.get("college_quality_lead_flag") or 0)

    session.clear()
    session.permanent = False
    session[SESSION_KEY] = True
    session[SESSION_USER] = canonical_user
    session["user_role"] = role
    session["is_supervisor"] = 1 if is_supervisor_flag == 1 else 0
    session["is_system_account"] = 1 if is_system_account_flag == 1 else 0
    session["is_dept_quality_coordinator"] = 1 if is_dept_quality_coordinator_flag == 1 else 0
    if role_profile_id_val not in (None, ""):
        try:
            session["role_profile_id"] = int(role_profile_id_val)
        except (TypeError, ValueError):
            pass
    if display_title_ar_val:
        session["display_title_ar"] = str(display_title_ar_val)
    session["is_college_quality_lead"] = 1 if college_quality_lead_flag == 1 else 0
    session["is_platform_admin"] = 1 if role == "system_admin" else 0
    session.pop(SESSION_ACTIVE_MODE, None)
    if role == "supervisor":
        session[SESSION_ACTIVE_MODE] = "supervisor"
    elif role == "instructor" and is_supervisor_flag == 1:
        session[SESSION_ACTIVE_MODE] = "instructor"
    elif role == "head_of_department":
        session[SESSION_ACTIVE_MODE] = "head"
    elif role == "college_dean":
        session[SESSION_ACTIVE_MODE] = "dean"
    elif role == "academic_vice_dean":
        session[SESSION_ACTIVE_MODE] = "vice_dean"
    session[SESSION_LOGIN_TIME] = str(os.times())
    session["_auth_fresh"] = True
    if student_id:
        session["student_id"] = student_id
    if role in ("supervisor", "instructor", "head_of_department", "college_dean", "academic_vice_dean"):
        try:
            if instructor_id:
                session["instructor_id"] = int(instructor_id)
            elif get_connection is not None:
                with get_connection() as conn:
                    cur = conn.cursor()
                    row = cur.execute(
                        "SELECT id FROM instructors WHERE name = ? LIMIT 1",
                        (canonical_user,),
                    ).fetchone()
                    if row:
                        session["instructor_id"] = int(row[0])
        except Exception:
            logger.exception("failed to bind supervisor to instructor_id")

    logger.info("User %s logged in successfully as role=%s", canonical_user, role)
    try:
        if login_user is not None and login_manager is not None:
            login_user(
                User(
                    username=canonical_user,
                    role=role,
                    student_id=student_id,
                    instructor_id=session.get("instructor_id"),
                ),
                remember=False,
            )
    except Exception:
        logger.exception("failed to login_user (Flask-Login)")
    session.permanent = False
    if wants_json:
        return jsonify({
            "status": "ok",
            "message": "تم تسجيل الدخول بنجاح",
            "user": canonical_user,
            "role": role,
        }), 200
    if role in ("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department"):
        target = "/dashboard?logged_in=1"
    elif role == "student" and student_id:
        target = "/my_portal?logged_in=1"
    elif role in ("supervisor",) or (role == "instructor" and is_supervisor_flag == 1):
        target = "/supervisor_dashboard?logged_in=1"
    elif role == "instructor":
        target = "/my_courses?logged_in=1"
    else:
        target = "/?logged_in=1"
    resp = make_response(_redirect(target))
    secure = os.environ.get("FLASK_ENV") == "production"
    _purge_legacy_auth_cookies(resp)
    resp.set_cookie(
        LOGIN_PROBE_COOKIE,
        "1",
        max_age=20,
        secure=secure,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return resp


def login_required(f):
    """ديكوراتور للمصادقة - يتطلب تسجيل الدخول.

    - طلبات المتصفح العادية: تحويل إلى /login.
    - طلبات API / fetch / JSON: ترجع JSON 401 كما هو.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        is_logged_in = _session_is_logged_in()
        if not is_logged_in:
            # تحديد ما إذا كان الطلب API/JSON أو من Ajax/fetch
            accept = (request.headers.get("Accept") or "").lower()
            is_api_request = (
                request.is_json
                or "application/json" in accept
                or request.path.startswith("/api/")
                or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            )
            if is_api_request:
                return jsonify({
                    'status': 'error',
                    'message': 'يجب تسجيل الدخول للوصول إلى هذه الصفحة',
                    'code': 'UNAUTHORIZED'
                }), 401
            # طلب متصفح عادي → تحويل إلى صفحة تسجيل الدخول
            return _redirect_to_login()
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """ديكوراتور للمصادقة - يتطلب صلاحيات إدارية"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        is_logged_in = _session_is_logged_in()
        if not is_logged_in:
            return jsonify({
                'status': 'error',
                'message': 'يجب تسجيل الدخول للوصول إلى هذه الصفحة',
                'code': 'UNAUTHORIZED'
            }), 401
        # يمكن إضافة فحص الصلاحيات هنا لاحقاً
        user_role = None
        if current_user is not None:
            try:
                if current_user.is_authenticated:
                    user_role = getattr(current_user, "role", None)
            except Exception:
                user_role = None
        if not user_role:
            user_role = session.get('user_role', 'user')
        user_role = _normalize_role(user_role)
        if user_role != "admin_main":
            return jsonify({
                'status': 'error',
                'message': 'ليس لديك صلاحيات كافية',
                'code': 'FORBIDDEN'
            }), 403
        return f(*args, **kwargs)
    return decorated_function


def role_required(*roles):
    """ديكوراتور للتحقق من أن المستخدم يملك أحد الأدوار المحددة."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            is_logged_in = _session_is_logged_in()
            if not is_logged_in:
                accept = (request.headers.get("Accept") or "").lower()
                is_api_request = (
                    request.is_json
                    or "application/json" in accept
                    or request.path.startswith("/api/")
                    or request.headers.get("X-Requested-With") == "XMLHttpRequest"
                )
                if is_api_request:
                    return jsonify({
                        'status': 'error',
                        'message': 'يجب تسجيل الدخول للوصول إلى هذه الصفحة',
                        'code': 'UNAUTHORIZED'
                    }), 401
                return _redirect_to_login()
            user_role = None
            if current_user is not None:
                try:
                    if current_user.is_authenticated:
                        user_role = getattr(current_user, "role", None)
                except Exception:
                    user_role = None
            if not user_role:
                user_role = session.get('user_role')
            normalized_allowed = {_normalize_role(r) for r in roles}
            effective = _effective_roles(user_role)
            if _dual_role_admin_blocked_path(
                request.path,
                user_role or "",
                session.get(SESSION_ACTIVE_MODE),
            ):
                accept = (request.headers.get("Accept") or "").lower()
                is_api_request = (
                    request.is_json
                    or "application/json" in accept
                    or request.path.startswith("/api/")
                    or request.headers.get("X-Requested-With") == "XMLHttpRequest"
                )
                if is_api_request:
                    return jsonify({
                        'status': 'error',
                        'message': 'صفحات الإدارة والإعدادات محصورة على المسؤول الرئيسي',
                        'code': 'FORBIDDEN'
                    }), 403
                return (
                    "<h3>403 Forbidden</h3><p>صفحات الإدارة والإعدادات محصورة على المسؤول الرئيسي.</p>",
                    403,
                    {"Content-Type": "text/html; charset=utf-8"},
                )
            if not (effective & normalized_allowed):
                accept = (request.headers.get("Accept") or "").lower()
                is_api_request = (
                    request.is_json
                    or "application/json" in accept
                    or request.path.startswith("/api/")
                    or request.headers.get("X-Requested-With") == "XMLHttpRequest"
                )
                if is_api_request:
                    return jsonify({
                        'status': 'error',
                        'message': 'ليس لديك صلاحيات كافية لتنفيذ هذه العملية',
                        'code': 'FORBIDDEN'
                    }), 403
                return (
                    "<h3>403 Forbidden</h3><p>ليس لديك صلاحيات كافية لتنفيذ هذه العملية.</p>",
                    403,
                    {"Content-Type": "text/html; charset=utf-8"},
                )
            return f(*args, **kwargs)
        return wrapped
    return decorator


def is_college_quality_lead_session() -> bool:
    """رئيس ضمان الجودة بالكلية (علم في جدول users)."""
    try:
        return int(session.get("is_college_quality_lead") or 0) == 1
    except (TypeError, ValueError):
        return False


SURVEY_INVITE_MANAGE_ROLES = frozenset({"admin_main", "system_admin", "college_dean"})
SURVEY_RESULTS_VIEW_ROLES = frozenset(
    {
        "admin",
        "admin_main",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
        "head_of_department",
    }
)


def can_manage_survey_invites(user_role: str | None = None) -> bool:
    """إنشاء/إدارة روابط الاستبيانات الخارجية — عميد + أدمن رئيسي/نظام فقط."""
    if is_system_admin_session():
        return True
    role = _normalize_role((user_role or session.get("user_role") or "").strip())
    return role in SURVEY_INVITE_MANAGE_ROLES


def can_view_survey_results(user_role: str | None = None) -> bool:
    """عرض نتائج الاستبيانات — قيادة الكلية/القسم + رئيس ضمان الجودة بالكلية."""
    role = _normalize_role((user_role or session.get("user_role") or "").strip())
    if role in SURVEY_RESULTS_VIEW_ROLES:
        return True
    if role in SURVEY_INVITE_MANAGE_ROLES:
        return True
    return is_college_quality_lead_session()


def is_system_admin_session() -> bool:
    from backend.core.user_admin_policy import is_system_admin_session as _isa
    return _isa(session)


def is_college_dean_session() -> bool:
    from backend.core.user_admin_policy import is_college_dean_session as _icd
    return _icd(session)


def can_edit_accreditation_catalog(user_role: str | None = None) -> bool:
    """
    تعديل مصفوفة الأدلة الثابتة (أنواع + قواعد) — مستوى المؤسسة.
    """
    if is_system_admin_session():
        return True
    try:
        if int(session.get("is_platform_admin") or 0) == 1:
            return True
    except (TypeError, ValueError):
        pass
    role = _normalize_role((user_role or session.get("user_role") or "").strip())
    if role == "admin_main" and is_college_quality_lead_session():
        return True
    return False


def can_bind_accreditation_evidence(user_role: str | None = None) -> bool:
    """ربط المصادر الفعلية — رئيس قسم، منسق جودة، عميد، أو مسؤول."""
    if can_edit_accreditation_catalog(user_role):
        return True
    if is_college_dean_session():
        return True
    role = _normalize_role((user_role or session.get("user_role") or "").strip())
    if role == "academic_vice_dean":
        return True
    if role in ("admin", "admin_main"):
        return True
    if role == "head_of_department":
        return True
    if role == "instructor" and session.get("is_dept_quality_coordinator"):
        return True
    return False


def accreditation_evidence_binder_required(f):
    """ديكوراتور: ربط مصادر الأدلة (ب2–ب3)."""

    @wraps(f)
    def wrapped(*args, **kwargs):
        is_logged_in = bool(session.get(SESSION_KEY, False))
        if not is_logged_in:
            return jsonify({
                "status": "error",
                "message": "يجب تسجيل الدخول للوصول إلى هذه الصفحة",
                "code": "UNAUTHORIZED",
            }), 401
        if not can_bind_accreditation_evidence():
            return jsonify({
                "status": "error",
                "message": "ربط الأدلة محصور على رئيس القسم أو منسق الجودة أو إدارة الكلية",
                "code": "FORBIDDEN",
            }), 403
        return f(*args, **kwargs)

    return wrapped


def accreditation_catalog_editor_required(f):
    """ديكوراتور: تعديل كتالوج مصفوفة الأدلة (admin أو رئيس جودة الكلية)."""

    @wraps(f)
    def wrapped(*args, **kwargs):
        is_logged_in = bool(session.get(SESSION_KEY, False))
        if not is_logged_in:
            accept = (request.headers.get("Accept") or "").lower()
            is_api_request = (
                request.is_json
                or "application/json" in accept
                or request.path.startswith("/api/")
                or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            )
            if is_api_request:
                return jsonify({
                    "status": "error",
                    "message": "يجب تسجيل الدخول للوصول إلى هذه الصفحة",
                    "code": "UNAUTHORIZED",
                }), 401
            return redirect("/login")
        if not can_edit_accreditation_catalog():
            return jsonify({
                "status": "error",
                "message": "تعديل مصفوفة الأدلة محصور على المسؤول أو رئيس ضمان الجودة بالكلية",
                "code": "FORBIDDEN",
            }), 403
        return f(*args, **kwargs)

    return wrapped


def init_auth(app):
    """تهيئة نظام المصادقة"""
    # استخدام المفتاح السري من الإعدادات
    app.secret_key = SECRET_KEY
    
    # إعدادات الجلسة
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=SESSION_LIFETIME_MINUTES)
    app.config['SESSION_COOKIE_NAME'] = os.environ.get('SESSION_COOKIE_NAME', SESSION_COOKIE_NAME)
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    if os.environ.get('FLASK_ENV') == 'production':
        app.config['PREFERRED_URL_SCHEME'] = 'https'
    _cookie_domain = (os.environ.get('SESSION_COOKIE_DOMAIN') or '').strip()
    if _cookie_domain:
        if not _cookie_domain.startswith('.'):
            _cookie_domain = '.' + _cookie_domain
        app.config['SESSION_COOKIE_DOMAIN'] = _cookie_domain
        app.config['REMEMBER_COOKIE_DOMAIN'] = _cookie_domain
        app.config['REMEMBER_COOKIE_SECURE'] = app.config['SESSION_COOKIE_SECURE']
        app.config['REMEMBER_COOKIE_HTTPONLY'] = True
        app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
    
    # Blueprint للمصادقة
    from flask import Blueprint
    auth_bp = Blueprint('auth', __name__)

    # تهيئة Flask-Login (ترقية تدريجية)
    try:
        if login_manager is not None:
            login_manager.init_app(app)
    except Exception:
        logger.exception("failed to init Flask-Login")

    _login_rl_enabled = (os.environ.get("FLASK_ENV") or "").strip().lower() == "production"
    try:
        _login_rl_max = max(5, int(os.environ.get("LOGIN_RATE_LIMIT_MAX", "20")))
    except ValueError:
        _login_rl_max = 20
    try:
        _login_rl_win = max(10, int(os.environ.get("LOGIN_RATE_LIMIT_WINDOW", "60")))
    except ValueError:
        _login_rl_win = 60

    @auth_bp.route('/login', methods=['POST'])
    @rate_limit(
        max_requests=_login_rl_max,
        window_seconds=_login_rl_win,
        enabled=_login_rl_enabled,
    )
    def login():
        """تسجيل الدخول (JSON API أو form POST مع redirect)."""
        ct = (request.content_type or "").lower()
        accept = (request.headers.get("Accept") or "").lower()
        wants_json = (
            request.is_json
            or "application/json" in ct
            or ("application/json" in accept and "text/html" not in accept)
        )
        data = request.get_json(silent=True) if wants_json else None
        if not data:
            data = request.form
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        remember = bool(data.get("remember", False))

        def _err(message, code, status=400):
            if wants_json:
                return jsonify({"status": "error", "message": message, "code": code}), status
            from flask import redirect as _redirect, url_for as _url_for
            return _redirect(_url_for("login_page", error=code))

        # التحقق من البيانات المطلوبة
        if not username or not password:
            return _err("اسم المستخدم وكلمة المرور مطلوبان", "MISSING_CREDENTIALS", 400)

        from backend.core.auth_throttle import (
            is_locked,
            lockout_enabled,
            record_login_failure,
            record_login_success,
        )

        if lockout_enabled():
            locked, _retry = is_locked(username)
            if locked:
                logger.warning("Login blocked by lockout username=%s", username)
                return _err("تم تجاوز عدد المحاولات. حاول لاحقاً.", "ACCOUNT_LOCKED", 429)
        
        # التحقق من بيانات الدخول وتحديد الدور
        role = None
        student_id = None
        is_supervisor_flag = 0
        is_system_account_flag = 0
        role_profile_id_val = None
        display_title_ar_val = None
        is_dept_quality_coordinator_flag = 0
        college_quality_lead_flag = 0
        instructor_id = None
        db_role = None
        # اسم المستخدم المعياري من عمود users.username (ضروري لمزامنة الجلسة مع قاعدة البيانات
        # ولـ POST /auth/active_mode؛ لا يُستخدم المُدخل الخام إذا وُجد الصف عبر student_id/instructor_id)
        username_db = None

        # 1) حاول التحقق من جدول users إن توفر
        users_count = None
        if get_connection is not None:
            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    # دعم تسجيل الدخول بـ username أو student_id أو instructor_id
                    row = _fetch_user_login_row(cur, username)
                    if not row:
                        # fallback: student_id or instructor_id
                        try:
                            row = cur.execute(
                                "SELECT username, password_hash, role, student_id, instructor_id, "
                                "COALESCE(is_active,1) AS is_active, COALESCE(is_supervisor,0) AS is_supervisor, "
                                "COALESCE(is_college_quality_lead,0) AS is_college_quality_lead "
                                "FROM users WHERE student_id = ? OR CAST(instructor_id AS TEXT) = ?",
                                (username, username),
                            ).fetchone()
                        except Exception:
                            try:
                                cur.connection.rollback()
                            except Exception:
                                pass
                            row = cur.execute(
                                "SELECT username, password_hash, role, student_id, instructor_id, "
                                "COALESCE(is_active,1) AS is_active, COALESCE(is_supervisor,0) AS is_supervisor, "
                                "0 AS is_college_quality_lead "
                                "FROM users WHERE student_id = ? OR CAST(instructor_id AS TEXT) = ?",
                                (username, username),
                            ).fetchone()
                    if row:
                        # فهرس ثابت يعمل مع sqlite3.Row و psycopg (dict_row)
                        pw_hash = row[1]
                        db_role = row[2]
                        db_student_id = row[3]
                        db_instructor_id = row[4]
                        db_is_active = row[5]
                        db_is_supervisor = row[6]
                        db_college_quality_lead = row[7] if len(row) > 7 else 0
                        if int(db_is_active or 1) == 0:
                            return _err("تم تعطيل هذا الحساب", "ACCOUNT_DISABLED", 403)
                        ok = verify_password(password, pw_hash)
                        if ok:
                            username_db = str(row[0] or "").strip()
                            # ترقية تلقائية للهاش القديم إلى Werkzeug
                            try:
                                if generate_password_hash is not None and not (pw_hash.startswith("pbkdf2:") or pw_hash.startswith("scrypt:")):
                                    new_hash = generate_password_hash(password)
                                    cur.execute(
                                        "UPDATE users SET password_hash = ? WHERE username = ?",
                                        (new_hash, username_db),
                                    )
                                    conn.commit()
                            except Exception:
                                logger.exception("failed to rehash legacy password")
                            role = db_role
                            student_id = db_student_id
                            instructor_id = db_instructor_id
                            try:
                                is_supervisor_flag = int(db_is_supervisor or 0)
                            except Exception:
                                is_supervisor_flag = 0
                            try:
                                college_quality_lead_flag = int(db_college_quality_lead or 0)
                            except Exception:
                                college_quality_lead_flag = 0
                            if len(row) > 8:
                                try:
                                    is_system_account_flag = int(row[8] or 0)
                                except (TypeError, ValueError):
                                    is_system_account_flag = 0
                            if len(row) > 9:
                                role_profile_id_val = row[9]
                            if len(row) > 10:
                                display_title_ar_val = row[10]
                            if len(row) > 11:
                                try:
                                    is_dept_quality_coordinator_flag = int(row[11] or 0)
                                except (TypeError, ValueError):
                                    is_dept_quality_coordinator_flag = 0
            except Exception:
                logger.exception("login: failed to query users table")
                if users_count is None:
                    users_count = 0

        # 2) bootstrap فقط إذا لم يُعثر على مستخدم — COUNT(*) مرة واحدة عند الحاجة
        if role is None and get_connection is not None:
            try:
                with get_connection() as conn:
                    row_cnt = conn.cursor().execute("SELECT COUNT(*) FROM users").fetchone()
                    users_count = row_cnt[0] if row_cnt else 0
            except Exception:
                users_count = 0

        if role is None and users_count == 0:
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                role = "system_admin"
                is_system_account_flag = 1
                try:
                    if get_connection is not None:
                        with get_connection() as conn2:
                            cur2 = conn2.cursor()
                            cur2.execute(
                                """
                                INSERT INTO users (username, password_hash, role, is_system_account)
                                VALUES (?, ?, 'system_admin', 1)
                                ON CONFLICT (username) DO NOTHING
                                """,
                                (ADMIN_USERNAME, hash_password(ADMIN_PASSWORD)),
                            )
                            conn2.commit()
                except Exception:
                    logger.exception("failed to seed admin user into users table")

        if role is None:
            if lockout_enabled():
                now_locked, _retry = record_login_failure(username)
                if now_locked:
                    return _err("تم تجاوز عدد المحاولات. حاول لاحقاً.", "ACCOUNT_LOCKED", 429)
            logger.warning("Failed login attempt for user: %s", username)
            return _err("اسم المستخدم أو كلمة المرور غير صحيحة", "INVALID_CREDENTIALS", 401)

        from backend.core.user_admin_policy import resolve_user_role_from_db
        role = resolve_user_role_from_db(db_role or role, is_system_account_flag)
        canonical_user = (username_db or username).strip()
        if lockout_enabled():
            record_login_success(canonical_user or username)
        login_ctx = {
            "canonical_user": canonical_user,
            "role": role,
            "student_id": student_id,
            "instructor_id": instructor_id,
            "is_supervisor_flag": int(is_supervisor_flag or 0),
            "is_system_account_flag": int(is_system_account_flag or 0),
            "is_dept_quality_coordinator_flag": int(is_dept_quality_coordinator_flag or 0),
            "role_profile_id_val": role_profile_id_val,
            "display_title_ar_val": display_title_ar_val,
            "college_quality_lead_flag": int(college_quality_lead_flag or 0),
        }
        from backend.core.mfa import intercept_login_mfa
        totp_code = str(data.get("totp") or data.get("mfa_code") or "")
        mfa_resp = intercept_login_mfa(login_ctx, totp_code=totp_code, wants_json=wants_json)
        if mfa_resp is not None:
            return mfa_resp
        return complete_login_session(login_ctx, wants_json=wants_json)

    @auth_bp.route('/invite/<token>', methods=['GET'])
    def invite_page(token):
        # صفحة بسيطة لتعيين كلمة المرور لأول مرة
        from flask import render_template
        return render_template("set_password.html", token=token)

    @auth_bp.route('/invite/<token>', methods=['POST'])
    def invite_set_password(token):
        data = request.get_json(force=True) or {}
        password_new = data.get("password") or ""
        from backend.core.password_policy import validate_new_password

        ok_pw, pw_err = validate_new_password(password_new)
        if not ok_pw:
            return jsonify({"status": "error", "message": pw_err, "code": "VALIDATION_ERROR"}), 400

        import hashlib
        token_hash = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
        from datetime import datetime
        now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

        if get_connection is None:
            return jsonify({"status": "error", "message": "DB غير متاح"}), 500
        with get_connection() as conn:
            cur = conn.cursor()
            inv = cur.execute(
                """
                SELECT id, username, email, expires_at, used_at
                FROM user_invites
                WHERE token_hash = ?
                LIMIT 1
                """,
                (token_hash,),
            ).fetchone()
            if not inv:
                return jsonify({"status": "error", "message": "الرابط غير صالح"}), 404
            if inv["used_at"]:
                return jsonify({"status": "error", "message": "تم استخدام هذا الرابط مسبقاً"}), 400
            try:
                exp = inv["expires_at"] or ""
                exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                if datetime.utcnow().replace(tzinfo=exp_dt.tzinfo) > exp_dt:
                    return jsonify({"status": "error", "message": "انتهت صلاحية الرابط"}), 400
            except Exception:
                pass

            username_db = inv["username"]
            pw_hash = hash_password(password_new)
            cur.execute(
                "UPDATE users SET password_hash = ?, is_active = 1 WHERE username = ?",
                (pw_hash, username_db),
            )
            cur.execute(
                "UPDATE user_invites SET used_at = ? WHERE id = ?",
                (now, inv["id"]),
            )
            conn.commit()

        return jsonify({"status": "ok", "message": "تم تعيين كلمة المرور بنجاح. يمكنك تسجيل الدخول الآن."}), 200
    
    @auth_bp.route('/logout', methods=['POST'])
    def logout():
        """تسجيل الخروج"""
        from flask import make_response

        username = session.get(SESSION_USER, 'unknown')
        perform_logout()
        logger.info(f"User {username} logged out")
        resp = make_response(jsonify({
            'status': 'ok',
            'message': 'تم تسجيل الخروج بنجاح'
        }), 200)
        _clear_session_cookies(resp)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp
    
    @auth_bp.route('/check', methods=['GET'])
    def check_auth():
        """التحقق من حالة تسجيل الدخول"""
        is_authenticated = _session_is_logged_in()
        user = session.get(SESSION_USER, None) if is_authenticated else None
        role = session.get('user_role', None) if is_authenticated else None
        student_id_val = session.get('student_id', None) if is_authenticated else None
        instructor_id_val = session.get('instructor_id', None) if is_authenticated else None
        is_supervisor_val = session.get('is_supervisor', 0) if is_authenticated else 0
        if is_authenticated:
            if not session.pop('_auth_fresh', False):
                _sync_user_session_from_db(user or session.get(SESSION_USER))
            role = session.get("user_role")
            is_supervisor_val = session.get("is_supervisor", 0)
            student_id_val = session.get("student_id", student_id_val)
            instructor_id_val = session.get("instructor_id", instructor_id_val)
            raw_role = (role or "").strip()
            rn = _normalize_role(raw_role)
            if rn != raw_role:
                session["user_role"] = rn
                session.modified = True
            role = rn
        active_mode_val = session.get(SESSION_ACTIVE_MODE) if is_authenticated else None
        # جلسات قديمة قبل إضافة active_mode: اضبط القيمة الافتراضية حتى تُحسب الصلاحيات بشكل صحيح
        if is_authenticated:
            r0 = (role or "").strip()
            try:
                isv0 = int(is_supervisor_val or 0)
            except (TypeError, ValueError):
                isv0 = 0
            if active_mode_val is None:
                if r0 == "supervisor":
                    session[SESSION_ACTIVE_MODE] = "supervisor"
                    active_mode_val = "supervisor"
                elif r0 == "instructor" and isv0 == 1:
                    session[SESSION_ACTIVE_MODE] = "instructor"
                    active_mode_val = "instructor"
                elif r0 == "head_of_department":
                    session[SESSION_ACTIVE_MODE] = "head"
                    active_mode_val = "head"
                elif r0 == "college_dean":
                    session[SESSION_ACTIVE_MODE] = "dean"
                    active_mode_val = "dean"
                elif r0 == "academic_vice_dean":
                    session[SESSION_ACTIVE_MODE] = "vice_dean"
                    active_mode_val = "vice_dean"
        caps = None
        admin_dept_scope = None
        if is_authenticated:
            from backend.core.permissions import resolve_capabilities_for_user
            from backend.services.utilities import get_connection as _gc

            rp_id = session.get("role_profile_id")
            rp_code = session.get("role_profile_code")
            try:
                rp_id = int(rp_id) if rp_id not in (None, "") else None
            except (TypeError, ValueError):
                rp_id = None
            conn_ctx = _gc() if _gc else None
            if conn_ctx:
                with conn_ctx as conn:
                    caps = resolve_capabilities_for_user(
                        role=role,
                        is_supervisor_val=int(is_supervisor_val or 0),
                        active_mode=active_mode_val,
                        username=user,
                        role_profile_id=rp_id,
                        role_profile_code=rp_code,
                        is_system_account=int(session.get("is_system_account") or 0),
                        conn=conn,
                    )
            else:
                caps = resolve_capabilities_for_user(
                    role=role,
                    is_supervisor_val=int(is_supervisor_val or 0),
                    active_mode=active_mode_val,
                    username=user,
                    role_profile_id=rp_id,
                    role_profile_code=rp_code,
                    is_system_account=int(session.get("is_system_account") or 0),
                    conn=None,
                )
            admin_dept_scope = resolve_admin_department_scope_api_dict()

        resp = jsonify({
            'status': 'ok',
            'authenticated': is_authenticated,
            'user': user if is_authenticated else None,
            'role': role if is_authenticated else None,
            'is_supervisor': int(is_supervisor_val or 0) if is_authenticated else 0,
            'active_mode': active_mode_val if is_authenticated else None,
            'student_id': student_id_val if is_authenticated else None,
            'instructor_id': instructor_id_val if is_authenticated else None,
            'is_college_quality_lead': int(session.get('is_college_quality_lead') or 0) if is_authenticated else 0,
            'is_dept_quality_coordinator': int(session.get('is_dept_quality_coordinator') or 0) if is_authenticated else 0,
            'capabilities': caps,
            'admin_department_scope': admin_dept_scope,
        })
        # منع كاش الاستجابة — وإلا يبقى active_mode قديماً بعد التبديل ولا يتحدّث الشريط
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        return resp, 200

    @auth_bp.route("/active_mode", methods=["POST"])
    @login_required
    def set_active_mode():
        """تبديل وضع العمل: أستاذ/مشرف (حساب أستاذ مُشرف) أو رئيس قسم/أستاذ/مشرف."""
        data = request.get_json(force=True) or {}
        mode = (data.get("mode") or "").strip().lower()
        _sync_user_session_from_db(session.get(SESSION_USER))
        role = _normalize_role((session.get("user_role") or "").strip())
        try:
            isv = int(session.get("is_supervisor") or 0)
        except (TypeError, ValueError):
            isv = 0
        # صمام أمان: إذا بقي الدور غير صالح بعد المزامنة، حاول الإنقاذ من users
        # بالاعتماد على instructor_id (مفيد لحسابات ربطت عبر معرف التدريس).
        if role not in ("head_of_department", "instructor", "college_dean") and get_connection is not None:
            try:
                row = None
                user_hint = (session.get(SESSION_USER) or "").strip()
                iid_hint = session.get("instructor_id")
                with get_connection() as conn:
                    cur = conn.cursor()
                    if user_hint:
                        row = cur.execute(
                            """
                            SELECT role, COALESCE(is_supervisor,0) AS is_supervisor
                            FROM users
                            WHERE lower(username) = lower(?)
                            LIMIT 1
                            """,
                            (user_hint,),
                        ).fetchone()
                    if (not row) and iid_hint:
                        row = cur.execute(
                            """
                            SELECT role, COALESCE(is_supervisor,0) AS is_supervisor
                            FROM users
                            WHERE instructor_id = ?
                            ORDER BY COALESCE(is_active,1) DESC
                            LIMIT 1
                            """,
                            (iid_hint,),
                        ).fetchone()
                if row:
                    role_db = _normalize_role(str(row[0] or "").strip())
                    try:
                        isv_db = int(row[1] or 0)
                    except (TypeError, ValueError):
                        isv_db = 0
                    if role_db != role or isv_db != isv:
                        session["user_role"] = role_db
                        session["is_supervisor"] = 1 if isv_db == 1 else 0
                        session.modified = True
                        role = role_db
                        isv = isv_db
            except Exception:
                logger.exception("active_mode fallback sync failed")
        if role == "college_dean":
            allowed = ("dean", "instructor", "supervisor") if isv else ("dean", "instructor")
            if mode not in allowed:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "وضع غير صالح",
                            "code": "INVALID_MODE",
                        }
                    ),
                    400,
                )
            if mode in ("instructor", "supervisor") and not _session_has_instructor_id():
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "يجب ربط الحساب برقم عضو هيئة التدريس لتفعيل وضع الأستاذ/المشرف",
                            "code": "NO_INSTRUCTOR_ID",
                        }
                    ),
                    400,
                )
            prev = session.get(SESSION_ACTIVE_MODE)
            session[SESSION_ACTIVE_MODE] = mode
            session.modified = True
            user = session.get(SESSION_USER, "?")
            logger.info("active_mode_switch user=%s from=%s to=%s (college_dean)", user, prev, mode)
            try:
                from backend.core.permissions import compute_college_dean_capabilities
                caps = compute_college_dean_capabilities(mode, isv, has_instructor_id=_session_has_instructor_id())
            except Exception:
                logger.exception("compute_capabilities failed (dean active_mode)")
                session[SESSION_ACTIVE_MODE] = prev
                session.modified = True
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "خطأ داخلي عند حساب الصلاحيات بعد التبديل",
                            "code": "CAPS_ERROR",
                        }
                    ),
                    500,
                )
            out = jsonify(
                {
                    "status": "ok",
                    "active_mode": mode,
                    "capabilities": caps,
                }
            )
            out.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return out, 200
        if role == "academic_vice_dean":
            allowed = ("vice_dean", "instructor", "supervisor") if isv else ("vice_dean", "instructor")
            if mode not in allowed:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "وضع غير صالح",
                            "code": "INVALID_MODE",
                        }
                    ),
                    400,
                )
            if mode in ("instructor", "supervisor") and not _session_has_instructor_id():
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "يجب ربط الحساب برقم عضو هيئة تدريس لتفعيل وضع الأستاذ/المشرف",
                            "code": "NO_INSTRUCTOR_ID",
                        }
                    ),
                    400,
                )
            prev = session.get(SESSION_ACTIVE_MODE)
            session[SESSION_ACTIVE_MODE] = mode
            session.modified = True
            user = session.get(SESSION_USER, "?")
            logger.info("active_mode_switch user=%s from=%s to=%s (academic_vice_dean)", user, prev, mode)
            try:
                from backend.core.permissions import compute_academic_vice_dean_capabilities
                caps = compute_academic_vice_dean_capabilities(mode, isv, has_instructor_id=_session_has_instructor_id())
            except Exception:
                logger.exception("compute_capabilities failed (vice_dean active_mode)")
                session[SESSION_ACTIVE_MODE] = prev
                session.modified = True
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "خطأ داخلي عند حساب الصلاحيات بعد التبديل",
                            "code": "CAPS_ERROR",
                        }
                    ),
                    500,
                )
            out = jsonify(
                {
                    "status": "ok",
                    "active_mode": mode,
                    "capabilities": caps,
                }
            )
            out.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return out, 200
        if role == "head_of_department":
            if mode not in ("head", "instructor", "supervisor"):
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "وضع غير صالح",
                            "code": "INVALID_MODE",
                        }
                    ),
                    400,
                )
            prev = session.get(SESSION_ACTIVE_MODE)
            session[SESSION_ACTIVE_MODE] = mode
            session.modified = True
            user = session.get(SESSION_USER, "?")
            logger.info("active_mode_switch user=%s from=%s to=%s (head_of_department)", user, prev, mode)
            try:
                caps = compute_capabilities(role, isv, mode)
            except Exception:
                logger.exception("compute_capabilities failed (head active_mode)")
                session[SESSION_ACTIVE_MODE] = prev
                session.modified = True
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "خطأ داخلي عند حساب الصلاحيات بعد التبديل",
                            "code": "CAPS_ERROR",
                        }
                    ),
                    500,
                )
            out = jsonify(
                {
                    "status": "ok",
                    "active_mode": mode,
                    "capabilities": caps,
                }
            )
            out.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return out, 200
        if role != "instructor" or isv != 1:
            logger.warning(
                "active_mode_denied user=%s role_raw=%s role_norm=%s is_supervisor=%s requested_mode=%s",
                session.get(SESSION_USER, "?"),
                session.get("user_role"),
                role,
                session.get("is_supervisor"),
                mode,
            )
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "لا يمكن تبديل الوضع لهذا الحساب",
                        "code": "NOT_ALLOWED",
                    }
                ),
                400,
            )
        if mode not in ("instructor", "supervisor"):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "وضع غير صالح",
                        "code": "INVALID_MODE",
                    }
                ),
                400,
            )
        prev = session.get(SESSION_ACTIVE_MODE)
        session[SESSION_ACTIVE_MODE] = mode
        session.modified = True
        user = session.get(SESSION_USER, "?")
        logger.info("active_mode_switch user=%s from=%s to=%s", user, prev, mode)
        try:
            caps = compute_capabilities(role, isv, mode)
        except Exception:
            logger.exception("compute_capabilities failed (instructor active_mode)")
            session[SESSION_ACTIVE_MODE] = prev
            session.modified = True
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "خطأ داخلي عند حساب الصلاحيات بعد التبديل",
                        "code": "CAPS_ERROR",
                    }
                ),
                500,
            )
        out = jsonify(
            {
                "status": "ok",
                "active_mode": mode,
                "capabilities": caps,
            }
        )
        out.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return out, 200

    @auth_bp.route("/admin_department_scope", methods=["POST"])
    @login_required
    def set_admin_department_scope():
        """تعيين سياق قسم للمسؤول (تصفية بيانات) أو إلغاؤه ليشمل كل الكلية."""
        data = request.get_json(force=True) or {}
        raw_id = data.get("department_id")
        _sync_user_session_from_db(session.get(SESSION_USER))
        role = _normalize_role((session.get("user_role") or "").strip())
        if role not in _ADMIN_SCOPE_ROLES:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "غير مسموح",
                        "code": "FORBIDDEN",
                    }
                ),
                403,
            )
        if role == "staff":
            from backend.core.department_scope_policy import session_role_profile_scope_mode

            if session_role_profile_scope_mode() == "department":
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "حسابك مقيّد بقسم واحد ولا يمكن تغيير نطاق العرض.",
                            "code": "FORBIDDEN",
                        }
                    ),
                    403,
                )
        try:
            isv = int(session.get("is_supervisor") or 0)
        except (TypeError, ValueError):
            isv = 0
        am = session.get(SESSION_ACTIVE_MODE)

        if raw_id in (None, "", False, "all", "null"):
            session.pop(SESSION_ADMIN_DEPARTMENT_SCOPE_ID, None)
            session.modified = True
            try:
                from backend.core.department_scope_policy import invalidate_department_scope_list_caches

                invalidate_department_scope_list_caches()
            except Exception:
                pass
            try:
                caps = compute_capabilities(role, isv, am)
            except Exception:
                logger.exception("compute_capabilities failed (admin_department_scope clear)")
                caps = None
            out = jsonify(
                {
                    "status": "ok",
                    "admin_department_scope": None,
                    "capabilities": caps,
                }
            )
            out.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return out, 200

        try:
            iid = int(raw_id)
        except (TypeError, ValueError):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "department_id غير صالح",
                        "code": "INVALID",
                    }
                ),
                400,
            )

        if get_connection is None:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "قاعدة البيانات غير متاحة",
                        "code": "DB",
                    }
                ),
                500,
            )

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                row = cur.execute(
                    """
                    SELECT id, code, name_ar FROM departments
                    WHERE id = ? AND COALESCE(is_active, 1) = 1
                    LIMIT 1
                    """,
                    (iid,),
                ).fetchone()
            if not row:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "القسم غير موجود أو غير نشط",
                            "code": "NOT_FOUND",
                        }
                    ),
                    400,
                )
            session[SESSION_ADMIN_DEPARTMENT_SCOPE_ID] = iid
            session.modified = True
            try:
                from backend.core.department_scope_policy import invalidate_department_scope_list_caches

                invalidate_department_scope_list_caches()
            except Exception:
                pass
            if hasattr(row, "keys"):
                payload = {
                    "id": int(row["id"]),
                    "code": row["code"],
                    "name_ar": row["name_ar"],
                }
            else:
                payload = {"id": int(row[0]), "code": row[1], "name_ar": row[2]}
        except Exception:
            logger.exception("set_admin_department_scope failed")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "خطأ داخلي",
                        "code": "ERROR",
                    }
                ),
                500,
            )

        user = session.get(SESSION_USER, "?")
        logger.info(
            "admin_department_scope_set user=%s department_id=%s",
            user,
            payload.get("id"),
        )
        try:
            caps = compute_capabilities(role, isv, am)
        except Exception:
            logger.exception("compute_capabilities failed (admin_department_scope set)")
            caps = None
        out = jsonify(
            {
                "status": "ok",
                "admin_department_scope": payload,
                "capabilities": caps,
            }
        )
        out.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return out, 200

    @auth_bp.route("/admin_department_scope/status", methods=["GET"])
    @login_required
    def admin_department_scope_status():
        """ملخص محتوى نطاق القسم الحالي (لتنبيه الواجهة عند فراغ القائمة)."""
        _sync_user_session_from_db(session.get(SESSION_USER))
        role = _normalize_role((session.get("user_role") or "").strip())
        if role not in _ADMIN_SCOPE_ROLES:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "غير مسموح",
                        "code": "FORBIDDEN",
                    }
                ),
                403,
            )
        dept_id = get_admin_department_scope_id()
        if dept_id is None:
            out = jsonify(
                {
                    "status": "ok",
                    "scoped": False,
                    "student_count": None,
                    "course_count": None,
                    "is_empty": False,
                }
            )
            out.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return out, 200
        if get_connection is None:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "قاعدة البيانات غير متاحة",
                        "code": "DB",
                    }
                ),
                500,
            )
        try:
            from backend.core.department_scope_policy import department_scope_data_summary

            with get_connection() as conn:
                summary = department_scope_data_summary(conn, int(dept_id))
        except Exception:
            logger.exception("admin_department_scope_status failed")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "تعذّر قراءة ملخص النطاق",
                        "code": "DB",
                    }
                ),
                500,
            )
        out = jsonify({"status": "ok", "scoped": True, **summary})
        out.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return out, 200

    @auth_bp.route('/change_password', methods=['POST'])
    @login_required
    def change_password():
        """تغيير كلمة مرور الحساب المسجّل (جدول users). لا يُذكر مسار الأسرار."""
        data = request.get_json(silent=True)
        if not data:
            data = request.form
        current_pw = (data.get("current_password") or data.get("old_password") or "")
        new_pw = (data.get("new_password") or data.get("password") or "")
        confirm_pw = data.get("confirm_password") or data.get("password_confirm") or ""

        from backend.core.password_policy import validate_new_password

        ok_pw, pw_err = validate_new_password(new_pw, current=current_pw, confirm=confirm_pw)
        if not ok_pw:
            return jsonify({"status": "error", "message": pw_err, "code": "VALIDATION_ERROR"}), 400
        if not current_pw:
            return jsonify({
                "status": "error",
                "message": "كلمة المرور الحالية مطلوبة",
                "code": "MISSING_CREDENTIALS",
            }), 400

        username = (session.get(SESSION_USER) or session.get("username") or "").strip()
        if not username:
            return jsonify({
                "status": "error",
                "message": "يجب تسجيل الدخول للوصول إلى هذه الصفحة",
                "code": "UNAUTHORIZED",
            }), 401

        if get_connection is None:
            return jsonify({
                "status": "error",
                "message": "تعذر تغيير كلمة المرور. راجع مسؤول النظام.",
                "code": "SERVICE_UNAVAILABLE",
            }), 503

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                row = _fetch_user_login_row(cur, username)
                if not row:
                    logger.warning("change_password: no users row username=%s", username)
                    return jsonify({
                        "status": "error",
                        "message": "تعذر تغيير كلمة المرور. راجع مسؤول النظام.",
                        "code": "NOT_FOUND",
                    }), 400
                stored_user = str(row[0] or "").strip()
                pw_hash = row[1]
                if not verify_password(current_pw, pw_hash):
                    return jsonify({
                        "status": "error",
                        "message": "كلمة المرور الحالية غير صحيحة",
                        "code": "INVALID_CREDENTIALS",
                    }), 400
                cur.execute(
                    "UPDATE users SET password_hash = ? WHERE username = ?",
                    (hash_password(new_pw), stored_user),
                )
                conn.commit()
        except Exception:
            logger.exception("change_password failed username=%s", username)
            return jsonify({
                "status": "error",
                "message": "تعذر تغيير كلمة المرور. راجع مسؤول النظام.",
                "code": "INTERNAL_ERROR",
            }), 500

        logger.info("User %s changed password", username)
        return jsonify({
            "status": "ok",
            "message": "تم تغيير كلمة المرور بنجاح",
        }), 200

    def _mfa_pending_user() -> str:
        from backend.core.mfa import SESSION_MFA_PENDING, SESSION_MFA_USER
        if not session.get(SESSION_MFA_PENDING):
            return ""
        return (session.get(SESSION_MFA_USER) or "").strip()

    @auth_bp.route("/mfa/verify", methods=["POST"])
    def mfa_verify():
        from backend.core.mfa import SESSION_MFA_CTX, SESSION_MFA_SETUP, user_mfa_state
        from backend.core.totp import verify_totp
        from backend.core.auth_throttle import increment_window

        data = request.get_json(silent=True) or request.form or {}
        user = _mfa_pending_user()
        if not user or session.get(SESSION_MFA_SETUP):
            return jsonify({
                "status": "error",
                "message": "لا توجد عملية تحقق معلّقة",
                "code": "MFA_NOT_PENDING",
            }), 400
        fails = increment_window(f"mfa:{user.casefold()}", 300)
        if fails > 10:
            return jsonify({
                "status": "error",
                "message": "تم تجاوز عدد محاولات الرمز. حاول لاحقاً.",
                "code": "MFA_LOCKED",
            }), 429
        code = str(data.get("code") or data.get("totp") or data.get("mfa_code") or "")
        _enabled, secret = user_mfa_state(user)
        if not secret or not verify_totp(secret, code):
            return jsonify({
                "status": "error",
                "message": "رمز التحقق غير صحيح",
                "code": "INVALID_TOTP",
            }), 401
        login_ctx = session.get(SESSION_MFA_CTX) or {}
        if not isinstance(login_ctx, dict) or not login_ctx.get("canonical_user"):
            return jsonify({
                "status": "error",
                "message": "انتهت صلاحية جلسة التحقق. سجّل الدخول مجدداً.",
                "code": "MFA_EXPIRED",
            }), 400
        wants_json = request.is_json or "application/json" in (request.headers.get("Accept") or "")
        return complete_login_session(login_ctx, wants_json=wants_json)

    @auth_bp.route("/mfa/setup/start", methods=["POST"])
    def mfa_setup_start():
        from backend.core.mfa import (
            SESSION_MFA_SETUP,
            SESSION_MFA_SETUP_SECRET,
            role_requires_mfa,
        )
        from backend.core.totp import generate_secret, provisioning_qr_svg

        pending_user = _mfa_pending_user()
        logged_user = (session.get(SESSION_USER) or "").strip() if session.get(SESSION_KEY) else ""
        role = (session.get("user_role") or "").strip()
        if pending_user:
            if not session.get(SESSION_MFA_SETUP):
                return jsonify({
                    "status": "error",
                    "message": "هذا الحساب مفعّل مسبقاً. أدخل رمز التحقق.",
                    "code": "MFA_ALREADY_ENROLLED",
                }), 400
            user = pending_user
        elif logged_user and role_requires_mfa(role):
            user = logged_user
        else:
            return jsonify({
                "status": "error",
                "message": "غير مصرّح بتفعيل التحقق بخطوتين",
                "code": "FORBIDDEN",
            }), 403
        secret = generate_secret()
        session[SESSION_MFA_SETUP_SECRET] = secret
        session.modified = True
        return jsonify({
            "status": "ok",
            "secret": secret,
            "qr_svg": provisioning_qr_svg(secret, user),
            "username": user,
        }), 200

    @auth_bp.route("/mfa/setup/confirm", methods=["POST"])
    def mfa_setup_confirm():
        from backend.core.mfa import (
            SESSION_MFA_CTX,
            SESSION_MFA_SETUP,
            SESSION_MFA_SETUP_SECRET,
            role_requires_mfa,
            save_user_totp,
        )
        from backend.core.totp import verify_totp

        data = request.get_json(silent=True) or request.form or {}
        secret = (session.get(SESSION_MFA_SETUP_SECRET) or "").strip()
        pending_user = _mfa_pending_user()
        logged_user = (session.get(SESSION_USER) or "").strip() if session.get(SESSION_KEY) else ""
        role = (session.get("user_role") or "").strip()
        if pending_user and session.get(SESSION_MFA_SETUP):
            user = pending_user
        elif logged_user and role_requires_mfa(role):
            user = logged_user
        else:
            return jsonify({
                "status": "error",
                "message": "غير مصرّح بتفعيل التحقق بخطوتين",
                "code": "FORBIDDEN",
            }), 403
        if not secret:
            return jsonify({
                "status": "error",
                "message": "ابدأ إعداد التحقق بخطوتين أولاً",
                "code": "MFA_SETUP_NOT_STARTED",
            }), 400
        code = str(data.get("code") or data.get("totp") or "")
        if not verify_totp(secret, code):
            return jsonify({
                "status": "error",
                "message": "رمز التحقق غير صحيح",
                "code": "INVALID_TOTP",
            }), 401
        if not save_user_totp(user, secret):
            return jsonify({
                "status": "error",
                "message": "تعذر حفظ إعداد التحقق بخطوتين",
                "code": "INTERNAL_ERROR",
            }), 500
        session.pop(SESSION_MFA_SETUP_SECRET, None)
        if pending_user:
            login_ctx = session.get(SESSION_MFA_CTX) or {}
            if not isinstance(login_ctx, dict) or not login_ctx.get("canonical_user"):
                return jsonify({
                    "status": "error",
                    "message": "انتهت صلاحية جلسة التحقق. سجّل الدخول مجدداً.",
                    "code": "MFA_EXPIRED",
                }), 400
            wants_json = request.is_json or "application/json" in (request.headers.get("Accept") or "")
            return complete_login_session(login_ctx, wants_json=wants_json)
        return jsonify({
            "status": "ok",
            "message": "تم تفعيل التحقق بخطوتين",
        }), 200

    app.register_blueprint(auth_bp, url_prefix='/auth')

    from backend.core.mfa import register_mfa_pending_guard
    register_mfa_pending_guard(app)

    # إعفاء مسارات بلا جلسة فقط (تسجيل الدخول/الخروج). طلبات JSON مع كوكي الجلسة تبقى تحت CSRF.
    try:
        csrf = app.extensions.get("csrf")
        if csrf is not None:
            csrf.exempt(login)
            csrf.exempt(logout)
    except Exception:
        logger.exception("csrf.exempt(auth.login) failed")

    return auth_bp
