"""
نظام المصادقة المحسّن
يستخدم متغيرات البيئة لتخزين بيانات الدخول بشكل آمن
"""
import os
import sys
from functools import wraps
from flask import request, jsonify, session
import hashlib
import secrets
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

try:
    from backend.services.utilities import get_connection
except Exception:  # pragma: no cover - حماية فقط في حال مشاكل الاستيراد
    get_connection = None

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


def hash_password(password: str) -> str:
    """تشفير كلمة المرور باستخدام SHA-256 مع salt"""
    # في الإنتاج، يُفضل استخدام bcrypt أو argon2
    salt = "schedule_optimizer_salt_2024"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """التحقق من كلمة المرور"""
    return hash_password(password) == hashed


def login_required(f):
    """ديكوراتور للمصادقة - يتطلب تسجيل الدخول"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get(SESSION_KEY, False):
            return jsonify({
                'status': 'error',
                'message': 'يجب تسجيل الدخول للوصول إلى هذه الصفحة',
                'code': 'UNAUTHORIZED'
            }), 401
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """ديكوراتور للمصادقة - يتطلب صلاحيات إدارية"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get(SESSION_KEY, False):
            return jsonify({
                'status': 'error',
                'message': 'يجب تسجيل الدخول للوصول إلى هذه الصفحة',
                'code': 'UNAUTHORIZED'
            }), 401
        # يمكن إضافة فحص الصلاحيات هنا لاحقاً
        user_role = session.get('user_role', 'user')
        if user_role != 'admin':
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
            if not session.get(SESSION_KEY, False):
                return jsonify({
                    'status': 'error',
                    'message': 'يجب تسجيل الدخول للوصول إلى هذه الصفحة',
                    'code': 'UNAUTHORIZED'
                }), 401
            user_role = session.get('user_role')
            if user_role not in roles:
                return jsonify({
                    'status': 'error',
                    'message': 'ليس لديك صلاحيات كافية لتنفيذ هذه العملية',
                    'code': 'FORBIDDEN'
                }), 403
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
    
    @auth_bp.route('/login', methods=['POST'])
    def login():
        """تسجيل الدخول"""
        data = request.get_json(force=True) or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
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
                        if verify_password(password, pw_hash):
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
        session.clear()
        logger.info(f"User {username} logged out")
        return jsonify({
            'status': 'ok',
            'message': 'تم تسجيل الخروج بنجاح'
        }), 200
    
    @auth_bp.route('/check', methods=['GET'])
    def check_auth():
        """التحقق من حالة تسجيل الدخول"""
        is_authenticated = session.get(SESSION_KEY, False)
        return jsonify({
            'status': 'ok',
            'authenticated': is_authenticated,
            'user': session.get(SESSION_USER, None) if is_authenticated else None,
            'role': session.get('user_role', None) if is_authenticated else None
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
