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

SESSION_KEY = 'authenticated'
SESSION_USER = 'user'
SESSION_LOGIN_TIME = 'login_time'
# وضع العمل داخل الجلسة: أستاذ يملك صلاحية مشرف في DB يختار instructor | supervisor
SESSION_ACTIVE_MODE = "active_mode"


def _normalize_role(role: str) -> str:
    """تطبيع الأدوار لتوافق الإصدارات السابقة."""
    r = (role or "").strip()
    if r == "admin":
        return "admin_main"
    return r


def is_supervisor_effective_session(
    user_role: str | None,
    is_supervisor_db: int | None,
    active_mode: str | None,
) -> bool:
    """
    هل تعمل الجلسة حالياً بوصف «مشرف» (صلاحيات وواجهة الإشراف)؟
    - حساب بدور supervisor: دائماً نعم.
    - أستاذ + is_supervisor في قاعدة البيانات: يعتمد على active_mode (افتراضي instructor).
    """
    r = (user_role or "").strip()
    if r == "supervisor":
        return True
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


def compute_capabilities(
    user_role: str | None,
    is_supervisor_val: int | None,
    active_mode: str | None = None,
) -> dict:
    """
    قدرات الواجهة (مصدر الخادم) — تفضّل استخدامها بدل مقارنة سلاسل الدور في JavaScript.

    تُحاكي منطق ``base_nav.html`` السابق مع إمكانية التوسعة دون تغيير كل قالب.
    """
    role = (user_role or "").strip()
    try:
        isv = int(is_supervisor_val or 0) == 1
    except (TypeError, ValueError):
        isv = False

    is_supervisor_effective = is_supervisor_effective_session(role, is_supervisor_val, active_mode)
    staff_planning = role in ("admin", "admin_main", "head_of_department")
    # مسودات الدرجات من القائمة العلوية: الإدارة/رئيس القسم فقط؛ الأستاذ يدخلها من «مقرراتي»
    show_grade_drafts = role in ("admin", "admin_main", "head_of_department")
    staff_quality = role in ("admin", "admin_main", "head_of_department")
    show_faculty_scorecards = staff_quality or role == "instructor"

    return {
        "v": 1,
        "nav_my_assigned_courses": role == "instructor",
        "nav_users_admin": role in ("admin", "admin_main"),
        "nav_supervision": role in ("admin", "admin_main"),
        "nav_academic_rules": role in ("admin", "admin_main"),
        "nav_course_registration_report": staff_planning,
        "nav_schedule_versions": staff_planning,
        "nav_exam_schedule_versions": staff_planning,
        "nav_grade_drafts": show_grade_drafts,
        "nav_course_closure_reports": staff_quality,
        "nav_faculty_scorecards": show_faculty_scorecards,
        "nav_faculty_final_dossier": staff_quality,
        "is_supervisor_effective": bool(is_supervisor_effective),
        # إخفاء عناصر إدارية عن فئة التدريس — لا يعتمد على وضع المشرف الفعّال
        "is_instructor_or_supervisor_nav": (role == "instructor")
        or (role == "supervisor")
        or isv,
        "can_switch_active_mode": (role == "instructor" and isv),
        "is_student": role == "student",
        "can_manage_schedule_edit": staff_planning,
        "can_manage_courses_edit": staff_planning,
        "can_manage_transcript_admin": staff_planning,
        # واجهة التنقل: أستاذ عادي يرى من «شؤون الطلبة» الحضور والغياب فقط
        "nav_student_affairs_attendance_only": (role == "instructor" and not is_supervisor_effective),
        # كشف الدرجات في القائمة — مخفي عن الأستاذ العادي (يُسمح للطالب والمشرف والإدارة)
        "nav_transcript_nav": staff_planning
        or (role == "student")
        or (role == "supervisor")
        or is_supervisor_effective,
    }


def _effective_roles(user_role: str) -> set:
    """
    إرجاع مجموعة الأدوار الفعلية للمستخدم (بدون خلط غير آمن).
    - instructor + is_supervisor=1 => يُضاف supervisor فقط عند active_mode=supervisor
    - supervisor (دور في DB) => تُضاف instructor للسماح بمسارات التدريس عند الحاجة
    """
    r = _normalize_role(user_role)
    roles = {r} if r else set()
    try:
        is_sup = int(session.get("is_supervisor") or 0)
    except Exception:
        is_sup = 0
    active = session.get(SESSION_ACTIVE_MODE)
    if r == "instructor" and is_sup == 1:
        if is_supervisor_effective_session(r, is_sup, active):
            roles.add("supervisor")
    if r == "supervisor":
        roles.add("instructor")
    # توحيد رئيس القسم مع المسؤول الرئيسي على مستوى الصلاحيات العامة.
    # الاستثناءات الخاصة بالإدارة/الإعدادات تُطبَّق بشكل صريح داخل role_required.
    if r == "head_of_department":
        roles.update({"admin_main", "admin"})
    return roles


def _head_of_department_blocked_path(path: str) -> bool:
    """مسارات الإدارة والإعدادات المحصورة على admin_main فقط."""
    p = (path or "").strip().lower()
    blocked_prefixes = (
        "/users",
        "/users_admin",
        "/admin/project_status",
        "/admin/backup_now",
        "/admin/system_diagnostics",
        "/admin/settings",
        "/academic_rules",
        "/academic_rules_page",
    )
    return any(p.startswith(prefix) for prefix in blocked_prefixes)

# إعداد Flask-Login (username هو المعرّف لأن جدول users يستخدمه كمفتاح أساسي)
login_manager = LoginManager() if LoginManager is not None else None
if login_manager is not None:
    login_manager.login_view = "login_page"  # endpoint في app.py لمسار /login
    login_manager.login_message = "يجب تسجيل الدخول للوصول إلى هذه الصفحة."


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


def hash_password(password: str) -> str:
    """تشفير كلمة المرور (Werkzeug إذا توفر، وإلا SHA-256 القديم مع salt)."""
    if generate_password_hash is not None:
        return generate_password_hash(password)
    salt = "schedule_optimizer_salt_2024"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """التحقق من كلمة المرور (يدعم الهاش الجديد + القديم)."""
    if not hashed:
        return False
    if (hashed.startswith("pbkdf2:") or hashed.startswith("scrypt:")) and check_password_hash is not None:
        return check_password_hash(hashed, password)
    salt = "schedule_optimizer_salt_2024"
    old_hash = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return old_hash == hashed


def login_required(f):
    """ديكوراتور للمصادقة - يتطلب تسجيل الدخول.

    - طلبات المتصفح العادية: تحويل إلى /login.
    - طلبات API / fetch / JSON: ترجع JSON 401 كما هو.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        is_logged_in = bool(session.get(SESSION_KEY, False))
        if not is_logged_in and current_user is not None:
            try:
                is_logged_in = bool(current_user.is_authenticated)
            except Exception:
                is_logged_in = False
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
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """ديكوراتور للمصادقة - يتطلب صلاحيات إدارية"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        is_logged_in = bool(session.get(SESSION_KEY, False))
        if not is_logged_in and current_user is not None:
            try:
                is_logged_in = bool(current_user.is_authenticated)
            except Exception:
                is_logged_in = False
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
            is_logged_in = bool(session.get(SESSION_KEY, False))
            if not is_logged_in and current_user is not None:
                try:
                    is_logged_in = bool(current_user.is_authenticated)
                except Exception:
                    is_logged_in = False
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
                return redirect("/login")
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
            if _normalize_role(user_role or "") == "head_of_department" and _head_of_department_blocked_path(request.path):
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


def init_auth(app):
    """تهيئة نظام المصادقة"""
    # استخدام المفتاح السري من الإعدادات
    app.secret_key = SECRET_KEY
    
    # إعدادات الجلسة
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=SESSION_LIFETIME_MINUTES)
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
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
        """تسجيل الدخول"""
        data = request.get_json(force=True) or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        remember = bool(data.get('remember', False))
        
        # التحقق من البيانات المطلوبة
        if not username or not password:
            return jsonify({
                'status': 'error',
                'message': 'اسم المستخدم وكلمة المرور مطلوبان',
                'code': 'MISSING_CREDENTIALS'
            }), 400
        
        # التحقق من بيانات الدخول وتحديد الدور
        role = None
        student_id = None
        is_supervisor_flag = 0

        # 1) حاول التحقق من جدول users إن توفر
        users_count = None
        if get_connection is not None:
            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    # احصل على عدد المستخدمين لمعرفة ما إذا كان الجدول فارغاً
                    try:
                        row_cnt = cur.execute("SELECT COUNT(*) FROM users").fetchone()
                        users_count = row_cnt[0] if row_cnt else 0
                    except Exception:
                        users_count = 0

                    # دعم تسجيل الدخول بـ username أو student_id أو instructor_id
                    row = cur.execute(
                        "SELECT username, password_hash, role, student_id, instructor_id, "
                        "COALESCE(is_active,1) AS is_active, COALESCE(is_supervisor,0) AS is_supervisor "
                        "FROM users WHERE username = ?",
                        (username,),
                    ).fetchone()
                    if not row:
                        # fallback: student_id or instructor_id
                        row = cur.execute(
                            "SELECT username, password_hash, role, student_id, instructor_id, "
                            "COALESCE(is_active,1) AS is_active, COALESCE(is_supervisor,0) AS is_supervisor "
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
                        if int(db_is_active or 1) == 0:
                            return jsonify({
                                'status': 'error',
                                'message': 'تم تعطيل هذا الحساب',
                                'code': 'ACCOUNT_DISABLED'
                            }), 403
                        ok = verify_password(password, pw_hash)
                        if ok:
                            # ترقية تلقائية للهاش القديم إلى Werkzeug
                            try:
                                if generate_password_hash is not None and not (pw_hash.startswith("pbkdf2:") or pw_hash.startswith("scrypt:")):
                                    new_hash = generate_password_hash(password)
                                    cur.execute(
                                        "UPDATE users SET password_hash = ? WHERE username = ?",
                                        (new_hash, username),
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
            except Exception:
                logger.exception("login: failed to query users table")
                if users_count is None:
                    users_count = 0

        # 2) إذا لم يكن هناك أي مستخدم في جدول users (bootstrap فقط)،
        #    اسمح بحساب admin من ملف الإعدادات كحالة خاصة أولية.
        if role is None and users_count == 0:
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                role = "admin"
                # seed admin into users table to support Flask-Login persistence
                try:
                    if get_connection is not None:
                        with get_connection() as conn2:
                            cur2 = conn2.cursor()
                            cur2.execute(
                                """
                                INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')
                                ON CONFLICT (username) DO NOTHING
                                """,
                                (ADMIN_USERNAME, hash_password(ADMIN_PASSWORD)),
                            )
                            conn2.commit()
                except Exception:
                    logger.exception("failed to seed admin user into users table")

        if role is None:
            logger.warning(f"Failed login attempt for user: {username}")
            return jsonify({
                'status': 'error',
                'message': 'اسم المستخدم أو كلمة المرور غير صحيحة',
                'code': 'INVALID_CREDENTIALS'
            }), 401

        session.permanent = True
        session[SESSION_KEY] = True
        session[SESSION_USER] = username
        session['user_role'] = role
        session['is_supervisor'] = 1 if int(is_supervisor_flag or 0) == 1 else 0
        session.pop(SESSION_ACTIVE_MODE, None)
        if role == "supervisor":
            session[SESSION_ACTIVE_MODE] = "supervisor"
        elif role == "instructor" and int(is_supervisor_flag or 0) == 1:
            session[SESSION_ACTIVE_MODE] = "instructor"
        session[SESSION_LOGIN_TIME] = str(os.times())
        if student_id:
            session['student_id'] = student_id
        # ربط حساب المشرف/المدرّس بسجل عضو هيئة تدريس (إن وُجد)
        if role in ("supervisor", "instructor"):
            try:
                # إذا جلبنا instructor_id من جدول users نستخدمه مباشرة
                if 'instructor_id' in locals() and instructor_id:
                    session['instructor_id'] = int(instructor_id)
                else:
                    # fallback: محاولة إيجاد مدرس بنفس اسم المستخدم
                    if get_connection is not None:
                        with get_connection() as conn:
                            cur = conn.cursor()
                            row = cur.execute(
                                "SELECT id FROM instructors WHERE name = ? LIMIT 1",
                                (username,),
                            ).fetchone()
                            if row:
                                session['instructor_id'] = int(row[0])
            except Exception:
                logger.exception("failed to bind supervisor to instructor_id")

        logger.info("User %s logged in successfully as role=%s", username, role)
        # تسجيل الدخول عبر Flask-Login (إن توفر) مع الحفاظ على الجلسة القديمة
        try:
            if login_user is not None and login_manager is not None:
                login_user(User(username=username, role=role, student_id=student_id, instructor_id=session.get('instructor_id')), remember=remember)
        except Exception:
            logger.exception("failed to login_user (Flask-Login)")
        return jsonify({
            'status': 'ok',
            'message': 'تم تسجيل الدخول بنجاح',
            'user': username,
            'role': role
        }), 200

    @auth_bp.route('/invite/<token>', methods=['GET'])
    def invite_page(token):
        # صفحة بسيطة لتعيين كلمة المرور لأول مرة
        from flask import render_template
        return render_template("set_password.html", token=token)

    @auth_bp.route('/invite/<token>', methods=['POST'])
    def invite_set_password(token):
        data = request.get_json(force=True) or {}
        password_new = data.get("password") or ""
        if not password_new or len(password_new) < 8:
            return jsonify({"status": "error", "message": "كلمة المرور يجب ألا تقل عن 8 أحرف"}), 400

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
        username = session.get(SESSION_USER, 'unknown')
        try:
            if logout_user is not None:
                logout_user()
        except Exception:
            logger.exception("failed to logout_user (Flask-Login)")
        # لا تستخدم session.clear() هنا لأن Flask-Login يحتاج وضع علامة لمسح cookie "تذكرني"
        # (logout_user يضع session['_remember']='clear' عند الحاجة).
        for k in (
            SESSION_KEY,
            SESSION_USER,
            SESSION_LOGIN_TIME,
            "user_role",
            "is_supervisor",
            "student_id",
            "instructor_id",
            SESSION_ACTIVE_MODE,
        ):
            try:
                session.pop(k, None)
            except Exception:
                pass
        logger.info(f"User {username} logged out")
        return jsonify({
            'status': 'ok',
            'message': 'تم تسجيل الخروج بنجاح'
        }), 200
    
    @auth_bp.route('/check', methods=['GET'])
    def check_auth():
        """التحقق من حالة تسجيل الدخول"""
        is_authenticated = session.get(SESSION_KEY, False)
        user = session.get(SESSION_USER, None) if is_authenticated else None
        role = session.get('user_role', None) if is_authenticated else None
        student_id_val = session.get('student_id', None) if is_authenticated else None
        instructor_id_val = session.get('instructor_id', None) if is_authenticated else None
        is_supervisor_val = session.get('is_supervisor', 0) if is_authenticated else 0
        if current_user is not None:
            try:
                if current_user.is_authenticated:
                    is_authenticated = True
                    user = getattr(current_user, "username", user)
                    role = getattr(current_user, "role", role)
                    student_id_val = getattr(current_user, "student_id", student_id_val)
                    instructor_id_val = getattr(current_user, "instructor_id", instructor_id_val)
            except Exception:
                pass
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
        caps = None
        if is_authenticated:
            caps = compute_capabilities(role, int(is_supervisor_val or 0), active_mode_val)

        return jsonify({
            'status': 'ok',
            'authenticated': is_authenticated,
            'user': user if is_authenticated else None,
            'role': role if is_authenticated else None,
            'is_supervisor': int(is_supervisor_val or 0) if is_authenticated else 0,
            'active_mode': active_mode_val if is_authenticated else None,
            'student_id': student_id_val if is_authenticated else None,
            'instructor_id': instructor_id_val if is_authenticated else None,
            'capabilities': caps,
        }), 200

    @auth_bp.route("/active_mode", methods=["POST"])
    @login_required
    def set_active_mode():
        """تبديل وضع العمل (أستاذ / مشرف) لحساب أستاذ يملك صلاحية مشرف في قاعدة البيانات."""
        data = request.get_json(force=True) or {}
        mode = (data.get("mode") or "").strip().lower()
        role = (session.get("user_role") or "").strip()
        try:
            isv = int(session.get("is_supervisor") or 0)
        except (TypeError, ValueError):
            isv = 0
        if role != "instructor" or isv != 1:
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
        user = session.get(SESSION_USER, "?")
        logger.info("active_mode_switch user=%s from=%s to=%s", user, prev, mode)
        caps = compute_capabilities(role, isv, mode)
        return (
            jsonify(
                {
                    "status": "ok",
                    "active_mode": mode,
                    "capabilities": caps,
                }
            ),
            200,
        )

    @auth_bp.route('/change_password', methods=['POST'])
    @login_required
    def change_password():
        """تغيير كلمة المرور (للمستقبل - يتطلب قاعدة بيانات للمستخدمين)"""
        return jsonify({
            'status': 'error',
            'message': 'هذه الميزة غير متاحة حالياً. يرجى تغيير كلمة المرور من ملف .env',
            'code': 'NOT_IMPLEMENTED'
        }), 501
    
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # fetch + JSON لا يمرّران دائماً بتحقق CSRF كما في النماذج؛ إعفاء تسجيل الدخول يمنع 400 بدون سبب واضح
    try:
        csrf = app.extensions.get("csrf")
        if csrf is not None:
            csrf.exempt(login)
            csrf.exempt(set_active_mode)
    except Exception:
        logger.exception("csrf.exempt(auth.login) failed")

    return auth_bp
