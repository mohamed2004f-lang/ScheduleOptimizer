"""
ملف الإعدادات المركزي - ScheduleOptimizer
يقرأ الإعدادات من متغيرات البيئة أو ملف .env
"""
import os
import secrets
from pathlib import Path

# تحميل متغيرات البيئة من ملف .env إذا كان موجوداً
try:
    from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
    # البحث عن ملف .env في المجلد الجذر للمشروع
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        # override=True لضمان أن القيم في .env هي المصدر الرئيسي
        load_dotenv(env_path, override=True)
except ImportError:
    # إذا لم تكن مكتبة python-dotenv مثبتة، نستمر بدونها
    pass

# ============================================
# إعدادات المصادقة
# ============================================
# يتم قراءتها من متغيرات البيئة أو ملف .env
# في حال عدم التعيين، يتم التحذير واستخدام قيم تطوير فقط
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin-mohamed')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')

if not ADMIN_PASSWORD:
    import warnings
    warnings.warn(
        "تحذير أمان: ADMIN_PASSWORD غير معيَّنة في متغيرات البيئة أو ملف .env. "
        "سيتم استخدام كلمة مرور افتراضية لأغراض التطوير فقط، ويجب تغييرها في الإنتاج.",
        UserWarning,
    )
    # كلمة مرور افتراضية للتطوير فقط
    ADMIN_PASSWORD = "change-me-now"

# ============================================
# إعدادات Flask
# ============================================
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    # توليد مفتاح عشوائي إذا لم يكن موجوداً (للتطوير فقط)
    SECRET_KEY = secrets.token_hex(32)
    import warnings
    warnings.warn(
        "⚠️ تحذير: لم يتم تعيين SECRET_KEY! تم توليد مفتاح مؤقت. "
        "في بيئة الإنتاج، يجب تعيين SECRET_KEY ثابت في متغيرات البيئة.",
        UserWarning
    )

FLASK_ENV = os.environ.get('FLASK_ENV', 'development')
FLASK_DEBUG = os.environ.get('FLASK_DEBUG', '1') == '1'

# ============================================
# إعدادات قاعدة البيانات
# ============================================
BASE_DIR = Path(__file__).parent
DATABASE_PATH = os.environ.get(
    'DATABASE_PATH', 
    str(BASE_DIR / 'backend' / 'database' / 'mechanical.db')
)

# ============================================
# إعدادات الأمان
# ============================================
# مدة صلاحية الجلسة بالدقائق
SESSION_LIFETIME_MINUTES = int(os.environ.get('SESSION_LIFETIME_MINUTES', '60'))

# إعدادات CSRF
WTF_CSRF_ENABLED = True
WTF_CSRF_TIME_LIMIT = 3600  # ساعة واحدة

# ============================================
# إعدادات التسجيل (Logging)
# ============================================
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
LOG_FILE = os.environ.get('LOG_FILE', 'logs/app.log')

# ============================================
# فئة الإعدادات للاستخدام مع Flask
# ============================================
class Config:
    """إعدادات Flask الأساسية"""
    SECRET_KEY = SECRET_KEY
    WTF_CSRF_ENABLED = WTF_CSRF_ENABLED
    WTF_CSRF_TIME_LIMIT = WTF_CSRF_TIME_LIMIT
    
    # إعدادات الجلسة
    PERMANENT_SESSION_LIFETIME = SESSION_LIFETIME_MINUTES * 60  # بالثواني
    SESSION_COOKIE_SECURE = FLASK_ENV == 'production'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'


class DevelopmentConfig(Config):
    """إعدادات بيئة التطوير"""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """إعدادات بيئة الإنتاج"""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True


class TestingConfig(Config):
    """إعدادات بيئة الاختبار"""
    DEBUG = True
    TESTING = True
    WTF_CSRF_ENABLED = False


# اختيار الإعدادات حسب البيئة
config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

def get_config():
    """الحصول على إعدادات البيئة الحالية"""
    return config_by_name.get(FLASK_ENV, DevelopmentConfig)
