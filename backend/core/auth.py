"""
نظام المصادقة الأساسي
"""
import os
import sys
from functools import wraps
from flask import request, jsonify, session
import hashlib
import secrets
import logging

logger = logging.getLogger(__name__)

# محاولة استيراد الإعدادات من config.py إذا كان موجوداً
try:
    # إضافة المجلد الجذر إلى المسار
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    from config import ADMIN_USERNAME, ADMIN_PASSWORD
    DEFAULT_USERNAME = ADMIN_USERNAME
    DEFAULT_PASSWORD = ADMIN_PASSWORD
    logger.info(f"Loaded credentials from config.py: username={DEFAULT_USERNAME}")
except ImportError:
    # إذا لم يوجد config.py، استخدم متغيرات البيئة أو القيم الافتراضية
    DEFAULT_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    DEFAULT_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    logger.info(f"Using environment/default credentials: username={DEFAULT_USERNAME}")

SESSION_KEY = 'authenticated'
SESSION_USER = 'user'


def hash_password(password):
    """تشفير كلمة المرور"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password, hashed):
    """التحقق من كلمة المرور"""
    return hash_password(password) == hashed


def login_required(f):
    """ديكوراتور للمصادقة - يتطلب تسجيل الدخول"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get(SESSION_KEY, False):
            return jsonify({
                'status': 'error',
                'message': 'يجب تسجيل الدخول للوصول إلى هذه الصفحة'
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
                'message': 'يجب تسجيل الدخول للوصول إلى هذه الصفحة'
            }), 401
        # يمكن إضافة فحص الصلاحيات هنا لاحقاً
        return f(*args, **kwargs)
    return decorated_function


def init_auth(app):
    """تهيئة نظام المصادقة"""
    # مفتاح سري للجلسات
    app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
    
    # Blueprint للمصادقة
    from flask import Blueprint
    auth_bp = Blueprint('auth', __name__)
    
    @auth_bp.route('/login', methods=['POST'])
    def login():
        """تسجيل الدخول"""
        data = request.get_json(force=True) or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        # التحقق من بيانات الدخول (مبسط - يمكن تحسينه لاحقاً)
        if username == DEFAULT_USERNAME and password == DEFAULT_PASSWORD:
            session[SESSION_KEY] = True
            session[SESSION_USER] = username
            logger.info(f"User {username} logged in")
            return jsonify({
                'status': 'ok',
                'message': 'تم تسجيل الدخول بنجاح'
            }), 200
        else:
            logger.warning(f"Failed login attempt for user: {username}")
            return jsonify({
                'status': 'error',
                'message': 'اسم المستخدم أو كلمة المرور غير صحيحة'
            }), 401
    
    @auth_bp.route('/logout', methods=['POST'])
    def logout():
        """تسجيل الخروج"""
        username = session.get(SESSION_USER, 'unknown')
        session.pop(SESSION_KEY, None)
        session.pop(SESSION_USER, None)
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
            'user': session.get(SESSION_USER, None) if is_authenticated else None
        }), 200
    
    app.register_blueprint(auth_bp, url_prefix='/auth')
    
    return auth_bp

