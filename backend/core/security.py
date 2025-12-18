"""
نظام الأمان المحسّن
يتضمن حماية CSRF، Rate Limiting، وتحقق من المدخلات
"""
import re
import logging
from functools import wraps
from flask import request, jsonify, g
from typing import Optional, Tuple, Any

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
    """محدد معدل الطلبات البسيط"""
    
    def __init__(self):
        self._requests = {}
    
    def is_allowed(self, key: str, max_requests: int = 100, window_seconds: int = 60) -> bool:
        """
        التحقق من أن المستخدم لم يتجاوز الحد المسموح
        """
        import time
        current_time = time.time()
        
        if key not in self._requests:
            self._requests[key] = []
        
        # إزالة الطلبات القديمة
        self._requests[key] = [
            t for t in self._requests[key] 
            if current_time - t < window_seconds
        ]
        
        if len(self._requests[key]) >= max_requests:
            return False
        
        self._requests[key].append(current_time)
        return True


# إنشاء instance عام
rate_limiter = RateLimiter()


def rate_limit(max_requests: int = 100, window_seconds: int = 60):
    """ديكوراتور لتحديد معدل الطلبات"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
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

def add_security_headers(response):
    """إضافة رؤوس الأمان للاستجابة"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Content Security Policy (يمكن تخصيصها حسب الحاجة)
    # response.headers['Content-Security-Policy'] = "default-src 'self'"
    
    return response


def init_security_headers(app):
    """تهيئة رؤوس الأمان"""
    @app.after_request
    def apply_security_headers(response):
        return add_security_headers(response)
    
    logger.info("Security headers initialized")
