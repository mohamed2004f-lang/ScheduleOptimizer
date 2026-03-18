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
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
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

def _normalize_role(role: str) -> str:
    """تطبيع الأدوار لتوافق الإصدارات السابقة."""
    r = (role or "").strip()
    if r == "admin":
        return "admin_main"
    if r == "supervisor":
        return "instructor"
    return r

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
                return jsonify({
                    'status': 'error',
                    'message': 'يجب تسجيل الدخول للوصول إلى هذه الصفحة',
                    'code': 'UNAUTHORIZED'
                }), 401
            user_role = None
            if current_user is not None:
                try:
                    if current_user.is_authenticated:
                        user_role = getattr(current_user, "role", None)
                except Exception:
                    user_role = None
            if not user_role:
                user_role = session.get('user_role')
            user_role = _normalize_role(user_role)
            normalized_allowed = {_normalize_role(r) for r in roles}
            if user_role not in normalized_allowed:
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
    
    @auth_bp.route('/login', methods=['POST'])
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

        # 1) حاول التحقق من جدول users إن توفر
        users_count = None
        if get_connection is not None:
            try:
                with get_connection() as conn:
                    conn.row_factory = None
                    cur = conn.cursor()
                    # احصل على عدد المستخدمين لمعرفة ما إذا كان الجدول فارغاً
                    try:
                        row_cnt = cur.execute("SELECT COUNT(*) FROM users").fetchone()
                        users_count = row_cnt[0] if row_cnt else 0
                    except Exception:
                        users_count = 0

                    row = cur.execute(
                        "SELECT username, password_hash, role, student_id, instructor_id FROM users WHERE username = ?",
                        (username,),
                    ).fetchone()
                    if row:
                        _, pw_hash, db_role, db_student_id, db_instructor_id = row
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
            except Exception:
                logger.exception("login: failed to query users table")

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
                                "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
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
        session[SESSION_LOGIN_TIME] = str(os.times())
        if student_id:
            session['student_id'] = student_id
        # ربط حساب المشرف بسجل عضو هيئة تدريس (إن وُجد)
        if role == "supervisor":
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
            "student_id",
            "instructor_id",
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
        return jsonify({
            'status': 'ok',
            'authenticated': is_authenticated,
            'user': user if is_authenticated else None,
            'role': role if is_authenticated else None,
            'student_id': student_id_val if is_authenticated else None,
            'instructor_id': instructor_id_val if is_authenticated else None,
        }), 200
    
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
    
    return auth_bp
