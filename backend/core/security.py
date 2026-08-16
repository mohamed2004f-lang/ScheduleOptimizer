"""
نظام الأمان المحسّن
يتضمن حماية CSRF، Rate Limiting، وتحقق من المدخلات
"""
import os
import re
import logging
from functools import wraps
from pathlib import Path
from flask import request, jsonify
from typing import Optional, Tuple, Any, Union

logger = logging.getLogger(__name__)


# ============================================
# حماية CSRF
# ============================================

def init_csrf(app):
    """تهيئة حماية CSRF"""
    try:
        from flask_wtf.csrf import CSRFProtect
        csrf = CSRFProtect()
        csrf.init_app(app)
        
        # استثناء بعض المسارات من CSRF إذا لزم الأمر (مثل API endpoints)
        @app.before_request
        def csrf_exempt_api():
            # يمكن إضافة استثناءات هنا للـ API endpoints
            pass
        
        logger.info("CSRF protection initialized")
        return csrf
    except ImportError:
        logger.warning("Flask-WTF not installed. CSRF protection disabled.")
        return None


# ============================================
# التحقق من المدخلات (Input Validation)
# ============================================

class InputValidator:
    """فئة للتحقق من صحة المدخلات"""
    
    @staticmethod
    def validate_student_id(sid: Any) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        التحقق من صحة رقم الطالب
        Returns: (is_valid, normalized_value, error_message)
        """
        if sid is None:
            return False, None, "رقم الطالب مطلوب"
        
        sid_str = str(sid).strip()
        if not sid_str:
            return False, None, "رقم الطالب مطلوب"
        
        if len(sid_str) > 50:
            return False, None, "رقم الطالب طويل جداً (الحد الأقصى 50 حرف)"
        
        # إزالة .0 من الأرقام المحولة من Excel
        if sid_str.endswith('.0'):
            sid_str = sid_str[:-2]
        
        return True, sid_str, None
    
    @staticmethod
    def validate_course_name(name: Any) -> Tuple[bool, Optional[str], Optional[str]]:
        """التحقق من صحة اسم المقرر"""
        if name is None:
            return False, None, "اسم المقرر مطلوب"
        
        name_str = str(name).strip()
        if not name_str:
            return False, None, "اسم المقرر مطلوب"
        
        if len(name_str) > 200:
            return False, None, "اسم المقرر طويل جداً (الحد الأقصى 200 حرف)"
        
        return True, name_str, None
    
    @staticmethod
    def validate_grade(grade: Any) -> Tuple[bool, Optional[float], Optional[str]]:
        """التحقق من صحة الدرجة"""
        if grade is None or grade == '':
            return True, None, None  # الدرجة اختيارية
        
        try:
            grade_float = float(grade)
        except (TypeError, ValueError):
            return False, None, "الدرجة يجب أن تكون رقماً"
        
        if grade_float < 0 or grade_float > 100:
            return False, None, "الدرجة يجب أن تكون بين 0 و 100"
        
        return True, grade_float, None
    
    @staticmethod
    def validate_time_slot(time_str: Any) -> Tuple[bool, Optional[str], Optional[str]]:
        """التحقق من صحة التوقيت (مثال: 08:00-09:30)"""
        if time_str is None:
            return False, None, "التوقيت مطلوب"
        
        time_str = str(time_str).strip()
        if not time_str:
            return False, None, "التوقيت مطلوب"
        
        # نمط التوقيت: HH:MM-HH:MM أو H:MM-H:MM
        pattern = r'^\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}$'
        if not re.match(pattern, time_str):
            return False, None, "تنسيق التوقيت غير صحيح. استخدم: HH:MM-HH:MM"
        
        return True, time_str, None
    
    @staticmethod
    def validate_day(day: Any) -> Tuple[bool, Optional[str], Optional[str]]:
        """التحقق من صحة اليوم"""
        if day is None:
            return False, None, "اليوم مطلوب"
        
        day_str = str(day).strip()
        if not day_str:
            return False, None, "اليوم مطلوب"
        
        # قائمة الأيام المسموح بها (عربي وإنجليزي)
        valid_days = {
            'السبت', 'الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة',
            'saturday', 'sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
            'sat', 'sun', 'mon', 'tue', 'wed', 'thu', 'fri'
        }
        
        if day_str.lower() not in {d.lower() for d in valid_days}:
            return False, None, f"اليوم غير صحيح. الأيام المسموح بها: {', '.join(sorted(valid_days))}"
        
        return True, day_str, None
    
    @staticmethod
    def validate_email(email: Any) -> Tuple[bool, Optional[str], Optional[str]]:
        """التحقق من صحة البريد الإلكتروني"""
        if email is None or email == '':
            return True, None, None  # البريد اختياري
        
        email_str = str(email).strip()
        
        # نمط بسيط للبريد الإلكتروني
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email_str):
            return False, None, "البريد الإلكتروني غير صحيح"
        
        return True, email_str, None
    
    @staticmethod
    def sanitize_string(value: Any, max_length: int = 500) -> str:
        """تنظيف النص من الأحرف الخطرة"""
        if value is None:
            return ""
        
        text = str(value).strip()
        
        # إزالة أحرف التحكم
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        
        # قص النص إذا كان طويلاً جداً
        if len(text) > max_length:
            text = text[:max_length]
        
        return text


# ============================================
# Rate Limiting (بسيط)
# ============================================

class RateLimiter:
    """محدد معدل الطلبات — Redis إن وُجد، وإلا ذاكرة العملية."""

    def is_allowed(self, key: str, max_requests: int = 100, window_seconds: int = 60) -> bool:
        from backend.core.auth_throttle import increment_window

        count = increment_window(f"ip:{key}", window_seconds)
        return count <= max_requests


# إنشاء instance عام
rate_limiter = RateLimiter()


def rate_limit(
    max_requests: int = 100,
    window_seconds: int = 60,
    *,
    enabled: bool = True,
):
    """ديكوراتور لتحديد معدل الطلبات (حسب عنوان IP). عند ``enabled=False`` يُعاد المسار دون قيد."""
    def decorator(f):
        if not enabled:
            return f

        @wraps(f)
        def decorated_function(*args, **kwargs):
            from flask import current_app
            if current_app.config.get("TESTING"):
                return f(*args, **kwargs)
            # استخدام IP كمفتاح
            key = request.remote_addr or 'unknown'

            if not rate_limiter.is_allowed(key, max_requests, window_seconds):
                logger.warning(f"Rate limit exceeded for {key}")
                return jsonify({
                    'status': 'error',
                    'message': 'تم تجاوز الحد المسموح من الطلبات. يرجى المحاولة لاحقاً.',
                    'code': 'RATE_LIMIT_EXCEEDED'
                }), 429

            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ============================================
# Security Headers
# ============================================

_SCRIPT_OPEN_RE = re.compile(r"<script(\s[^>]*)?>", re.IGNORECASE)


def csp_enabled() -> bool:
    v = (os.environ.get("ENABLE_CSP", "1") or "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return (os.environ.get("FLASK_ENV") or "").strip().lower() == "production"


def csp_legacy() -> bool:
    v = (os.environ.get("ENABLE_CSP_LEGACY") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def inject_script_nonces(html: str, nonce: str) -> str:
    """أضف nonce لكل وسم <script> يفتقده — يغطي السكربتات المضمّنة في القوالب."""
    if not html or not nonce:
        return html

    def _repl(match: re.Match) -> str:
        attrs = match.group(1) or ""
        if re.search(r"\bnonce\s*=", attrs, re.I):
            return match.group(0)
        return f'<script nonce="{nonce}"{attrs}>'

    return _SCRIPT_OPEN_RE.sub(_repl, html)


def _maybe_inject_html_nonces(response, nonce: str) -> None:
    if getattr(response, "direct_passthrough", False):
        return
    ctype = (response.content_type or "").lower()
    if "html" not in ctype:
        return
    try:
        data = response.get_data(as_text=True)
        updated = inject_script_nonces(data, nonce)
        if updated != data:
            response.set_data(updated)
    except Exception:
        logger.exception("CSP nonce injection failed")


def _csp_header_value(nonce: Optional[str] = None) -> Optional[str]:
    """
    سياسة CSP في الإنتاج. تعطيل: ENABLE_CSP=0
    الافتراضي: nonce بدون unsafe-inline/unsafe-eval في script-src.
    style-src يبقى مع unsafe-inline حتى يُجرَد CSS المضمّن في القوالب.
    ENABLE_CSP_LEGACY=1 يعيد السياسة القديمة إن تعطّلت صفحة.
    """
    if not csp_enabled():
        return None
    if csp_legacy() or not nonce:
        script = (
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://static.cloudflareinsights.com; "
        )
    else:
        script = (
            f"script-src 'self' 'nonce-{nonce}' "
            "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://static.cloudflareinsights.com; "
        )
    return (
        "default-src 'self'; "
        + script
        + "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "  # Bootstrap + أنماط القوالب؛ يُضيَّق بعد جرد القوالب
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' https://cloudflareinsights.com; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


def add_security_headers(response, nonce: Optional[str] = None):
    """إضافة رؤوس الأمان للاستجابة"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    csp = _csp_header_value(nonce)
    if csp:
        response.headers['Content-Security-Policy'] = csp
    if (os.environ.get("FLASK_ENV") or "").strip().lower() == "production":
        proto = ""
        try:
            proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
        except Exception:
            proto = ""
        if request.is_secure or proto == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

    return response


def init_security_headers(app):
    """تهيئة رؤوس الأمان + رمز CSP لكل طلب."""
    import secrets
    from flask import g

    @app.before_request
    def _assign_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.after_request
    def apply_security_headers(response):
        nonce = getattr(g, "csp_nonce", None)
        if nonce and csp_enabled() and not csp_legacy():
            _maybe_inject_html_nonces(response, nonce)
        return add_security_headers(response, nonce=nonce)

    logger.info("Security headers initialized")


# ============================================
# مسارات الرفع — منع الخروج من backend/uploads
# ============================================

def uploads_root() -> Path:
    """المجلد الجذر الوحيد المسموح لملفات المستخدم: backend/uploads."""
    return (Path(__file__).resolve().parent.parent / "uploads").resolve()


def _path_is_inside(child: Path, parent: Path) -> bool:
    """مقارنة مسارات محسومة مع مراعاة اختلاف حالة الأحرف على ويندوز."""
    child_s = os.path.normcase(str(child))
    parent_s = os.path.normcase(str(parent))
    if child_s == parent_s:
        return True
    prefix = parent_s if parent_s.endswith(os.sep) else parent_s + os.sep
    return child_s.startswith(prefix)


def resolve_safe_upload_path(
    stored_path: Optional[Union[str, os.PathLike]] = None,
    *,
    allowed_root: Optional[Union[str, os.PathLike]] = None,
) -> Optional[Path]:
    """
    أعد المسار المحسوم فقط إذا كان ملفاً موجوداً داخل ``backend/uploads``.

    إذا مُرّر ``allowed_root`` فيجب أن يكون هو أيضاً داخل مجلد الرفع، ويُقيَّد الملف به.
    يرفض المسارات الفارغة، والاختراق عبر ``..``، والروابط الرمزية الخارجة عن الجذر.
    """
    if stored_path is None:
        return None
    raw = str(stored_path).strip()
    if not raw:
        return None
    try:
        candidate = Path(raw).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if not candidate.is_file():
        return None

    root = uploads_root()
    if not _path_is_inside(candidate, root):
        logger.warning("Rejected download path outside uploads: %s", candidate)
        return None

    if allowed_root is not None:
        try:
            extra = Path(allowed_root).resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        if not _path_is_inside(extra, root):
            logger.warning("Rejected allowed_root outside uploads: %s", extra)
            return None
        if not _path_is_inside(candidate, extra):
            logger.warning("Rejected download path outside allowed_root: %s", candidate)
            return None

    return candidate


# توقيعات الملفات الثنائية — النص (.txt/.md/.json/.csv) يُقبل دون بصمة
_TEXT_UPLOAD_EXTS = frozenset({".txt", ".md", ".markdown", ".json", ".csv"})
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"
_UPLOAD_MAGICS: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".doc": (_OLE_MAGIC,),
    ".xls": (_OLE_MAGIC,),
    ".ppt": (_OLE_MAGIC,),
    ".docx": (_ZIP_MAGIC,),
    ".xlsx": (_ZIP_MAGIC,),
    ".pptx": (_ZIP_MAGIC,),
    ".zip": (_ZIP_MAGIC,),
}


def assert_upload_magic(raw: bytes, filename: str) -> None:
    """ارفض الملف إن لم يطابق باطنه الامتداد. الصيغ النصية تُستثنى."""
    ext = os.path.splitext((filename or "").strip())[1].lower()
    if not raw:
        raise ValueError("ملف فارغ")
    if ext in _TEXT_UPLOAD_EXTS:
        if b"\x00" in raw[:512]:
            raise ValueError("محتوى الملف لا يطابق الامتداد")
        return
    if ext == ".webp":
        if not (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"):
            raise ValueError("محتوى الملف لا يطابق الامتداد")
        return
    if ext == ".mp4":
        if raw[4:8] != b"ftyp":
            raise ValueError("محتوى الملف لا يطابق الامتداد")
        return
    if ext == ".webm":
        if not raw.startswith(b"\x1a\x45\xdf\xa3"):
            raise ValueError("محتوى الملف لا يطابق الامتداد")
        return
    magics = _UPLOAD_MAGICS.get(ext)
    if magics is None:
        return
    if not any(raw.startswith(sig) for sig in magics):
        raise ValueError("محتوى الملف لا يطابق الامتداد")
