"""
ملف الإعدادات المركزي - ScheduleOptimizer
يقرأ الإعدادات من متغيرات البيئة أو ملف .env
"""
import os
from pathlib import Path

# تحميل متغيرات البيئة من ملف .env إذا كان موجوداً
try:
    from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
    # البحث عن ملف .env في المجلد الجذر للمشروع
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        # افتراضياً في بيئة التطوير: .env هو مصدر الحقيقة لتجنّب متغيرات نظام قديمة/خاطئة
        # (مثل DATABASE_URL قديم)؛ يمكن تعطيل ذلك عبر DOTENV_OVERRIDE=0.
        _dotenv_override = (os.environ.get("DOTENV_OVERRIDE", "1") or "").strip().lower() in ("1", "true", "yes")
        load_dotenv(env_path, override=_dotenv_override)
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
    raise RuntimeError(
        "\n\n"
        "===== خطأ أمان حرج =====\n"
        "متغير البيئة ADMIN_PASSWORD غير معيَّن!\n"
        "يجب تعيين ADMIN_PASSWORD في ملف .env أو متغيرات البيئة قبل تشغيل التطبيق.\n"
        "مثال: ADMIN_PASSWORD=YourStr0ng!Passw0rd\n"
        "راجع ملف .env.example للتفاصيل.\n"
        "============================\n"
    )

# ============================================
# إعدادات Flask
# ============================================
SECRET_KEY = os.environ.get('SECRET_KEY')
_IS_PYTEST = bool(os.environ.get("PYTEST_CURRENT_TEST")) or (
    os.environ.get("FLASK_ENV") or ""
).strip().lower() in ("testing", "test")
if not SECRET_KEY:
    if _IS_PYTEST:
        SECRET_KEY = "test-secret-key-for-pytest"
    else:
        raise RuntimeError(
            "\n\n"
            "===== خطأ أمان حرج =====\n"
            "متغير البيئة SECRET_KEY غير معيَّن!\n"
            "يجب تعيين SECRET_KEY ثابت في ملف .env قبل التشغيل.\n"
            "مثال: SECRET_KEY=long-random-hex-or-phrase\n"
            "============================\n"
        )

FLASK_ENV = os.environ.get('FLASK_ENV', 'development')
FLASK_DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'
_FLASK_ENV_LOWER = (FLASK_ENV or "").strip().lower()
_IS_PRODUCTION = _FLASK_ENV_LOWER == "production"

# ============================================
# فحوصات أمان الإنتاج (أسرار + Redis)
# ============================================
_IN_DOCKER = os.path.exists("/.dockerenv")
if _IS_PRODUCTION and not _IS_PYTEST:
    if len(SECRET_KEY or "") < 32:
        raise RuntimeError(
            "\n\n===== خطأ أمان إنتاج =====\n"
            "SECRET_KEY قصير جداً (يلزم 32 حرفاً على الأقل في الإنتاج).\n"
            "ولّد مفتاحاً قوياً مثلاً:\n"
            "  python -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "============================\n"
        )
    _admin_pw = ADMIN_PASSWORD or ""
    try:
        from backend.core.password_policy import validate_new_password

        _pw_ok, _pw_err = validate_new_password(_admin_pw)
    except Exception:
        _pw_ok = (
            len(_admin_pw.strip()) >= 8
            and any(ch.isalpha() for ch in _admin_pw)
            and any(ch.isdigit() for ch in _admin_pw)
        )
        _pw_err = "يجب ألا تقل عن 8 أحرف وأن تحتوي حرفاً ورقماً"
    if not _pw_ok:
        raise RuntimeError(
            "\n\n===== خطأ أمان إنتاج =====\n"
            f"ADMIN_PASSWORD لا يستوفي سياسة كلمة المرور: {_pw_err}\n"
            "============================\n"
        )
    _redis_url = (
        (os.environ.get("CACHE_REDIS_URL") or os.environ.get("REDIS_URL") or "")
        .strip()
    )
    # داخل حاوية الإنتاج Redis إلزامي. على المضيف Compose يحقن
    # redis://redis:6379/0 تلقائياً حتى لو غاب من ملف .env.
    if not _redis_url and _IN_DOCKER:
        raise RuntimeError(
            "\n\n===== خطأ أمان إنتاج =====\n"
            "CACHE_REDIS_URL (أو REDIS_URL) إلزامي داخل حاوية الإنتاج.\n"
            "في Docker Compose يُضبط عادةً: redis://redis:6379/0\n"
            "============================\n"
        )

# ============================================
# إعدادات قاعدة البيانات
# ============================================
BASE_DIR = Path(__file__).parent
_RAW_DATABASE_URL = (os.environ.get('DATABASE_URL') or '').strip()

# Allow tests to run without a real PostgreSQL DB by letting them override env.
_IS_PYTEST = bool(os.environ.get("PYTEST_CURRENT_TEST"))
DATABASE_URL = _RAW_DATABASE_URL

if not _IS_PYTEST:
    if not _RAW_DATABASE_URL:
        raise RuntimeError(
            "\n\n===== إعدادات قاعدة البيانات =====\n"
            "يجب تعيين DATABASE_URL صراحةً إلى PostgreSQL.\n"
            "مثال: DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname\n"
            "============================\n"
        )
    _dbu = DATABASE_URL.strip().lower()
    if not (_dbu.startswith('postgresql://') or _dbu.startswith('postgresql+')):
        raise RuntimeError(
            "\n\n===== إعدادات قاعدة البيانات =====\n"
            "DATABASE_URL يجب أن يبدأ بـ postgresql:// أو postgresql+...\n"
            "============================\n"
        )

# ============================================
# إعدادات Connection Pool (لـ PostgreSQL فقط)
# ============================================
PG_POOL_MIN_SIZE = int(os.environ.get('PG_POOL_MIN_SIZE', '2'))
PG_POOL_MAX_SIZE = int(os.environ.get('PG_POOL_MAX_SIZE', '10'))

# ============================================
# إعدادات الأمان
# ============================================
# مدة صلاحية الجلسة بالدقائق
SESSION_LIFETIME_MINUTES = int(os.environ.get('SESSION_LIFETIME_MINUTES', '60'))

# إعدادات CSRF
WTF_CSRF_ENABLED = True
WTF_CSRF_TIME_LIMIT = 3600  # ساعة واحدة
# فحص Referer على HTTPS يرفض حفظاً صحيحاً إذا حجب المتصفح الترويسة (وكيل عكسي / خصوصية).
# الحماية الفعلية تبقى رمز الجلسة. للتفعيل: WTF_CSRF_SSL_STRICT=1
_wtf_ssl_strict = (os.environ.get("WTF_CSRF_SSL_STRICT") or "").strip().lower()
WTF_CSRF_SSL_STRICT = _wtf_ssl_strict in ("1", "true", "yes")

# ============================================
# إعدادات التسجيل (Logging)
# ============================================
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
LOG_FILE = os.environ.get('LOG_FILE', 'logs/app.log')

# تلميحات تقنية للمطوّر في الواجهة (نطاق القسم، phase0، …)
_show_dev_raw = (os.environ.get("SHOW_DEV_HINTS") or "").strip().lower()
if _show_dev_raw:
    SHOW_DEV_HINTS = _show_dev_raw in ("1", "true", "yes")
else:
    SHOW_DEV_HINTS = FLASK_DEBUG

# ============================================
# التخزين المؤقت والمهام الخلفية والتحسين
# ============================================
CACHE_TIMEOUT = int(os.environ.get('CACHE_TIMEOUT', '60'))
CACHE_TYPE = os.environ.get('CACHE_TYPE', 'SimpleCache')
CACHE_REDIS_URL = os.environ.get('CACHE_REDIS_URL', '')
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', '')
OPTIMIZER_USE_CPSAT = os.environ.get('OPTIMIZER_USE_CPSAT', '1')
OPTIMIZE_ASYNC_THRESHOLD = int(os.environ.get('OPTIMIZE_ASYNC_THRESHOLD', '50'))

# ============================================
# فئة الإعدادات للاستخدام مع Flask
# ============================================
class Config:
    """إعدادات Flask الأساسية"""
    SECRET_KEY = SECRET_KEY
    WTF_CSRF_ENABLED = WTF_CSRF_ENABLED
    WTF_CSRF_TIME_LIMIT = WTF_CSRF_TIME_LIMIT
    WTF_CSRF_SSL_STRICT = WTF_CSRF_SSL_STRICT
    
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
