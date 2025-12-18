"""
نظام التحقق من المدخلات
يوفر دوال وديكوراتورات للتحقق من صحة البيانات
"""
import re
import logging
from functools import wraps
from flask import request, jsonify
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """خطأ في التحقق من صحة البيانات"""
    def __init__(self, message: str, field: str = None):
        self.message = message
        self.field = field
        super().__init__(self.message)


def validate_required(data: Dict, fields: List[str]) -> List[str]:
    """
    التحقق من وجود الحقول المطلوبة
    Returns: قائمة بالحقول الناقصة
    """
    missing = []
    for field in fields:
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def validate_request_json(*required_fields):
    """
    ديكوراتور للتحقق من وجود الحقول المطلوبة في JSON request
    
    Usage:
        @validate_request_json('student_id', 'course_name')
        def my_route():
            data = request.get_json()
            # الآن نحن متأكدون أن student_id و course_name موجودان
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            data = request.get_json(force=True) or {}
            
            missing = validate_required(data, list(required_fields))
            if missing:
                return jsonify({
                    'status': 'error',
                    'message': f'الحقول التالية مطلوبة: {", ".join(missing)}',
                    'missing_fields': missing,
                    'code': 'VALIDATION_ERROR'
                }), 400
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


class Validators:
    """مجموعة من دوال التحقق"""
    
    @staticmethod
    def is_valid_student_id(sid: Any) -> bool:
        """التحقق من صحة رقم الطالب"""
        if sid is None:
            return False
        sid_str = str(sid).strip()
        return bool(sid_str) and len(sid_str) <= 50
    
    @staticmethod
    def is_valid_grade(grade: Any) -> bool:
        """التحقق من صحة الدرجة"""
        if grade is None or grade == '':
            return True  # الدرجة اختيارية
        try:
            g = float(grade)
            return 0 <= g <= 100
        except (TypeError, ValueError):
            return False
    
    @staticmethod
    def is_valid_units(units: Any) -> bool:
        """التحقق من صحة عدد الوحدات"""
        if units is None or units == '':
            return True  # اختياري
        try:
            u = int(units)
            return 0 <= u <= 20
        except (TypeError, ValueError):
            return False
    
    @staticmethod
    def is_valid_email(email: Any) -> bool:
        """التحقق من صحة البريد الإلكتروني"""
        if email is None or email == '':
            return True  # اختياري
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, str(email).strip()))
    
    @staticmethod
    def is_valid_phone(phone: Any) -> bool:
        """التحقق من صحة رقم الهاتف"""
        if phone is None or phone == '':
            return True  # اختياري
        # يقبل أرقام وشرطات ومسافات فقط
        pattern = r'^[\d\s\-\+\(\)]{7,20}$'
        return bool(re.match(pattern, str(phone).strip()))


def normalize_student_id(sid: Any) -> str:
    """تطبيع رقم الطالب"""
    if sid is None:
        return ""
    sid_str = str(sid).strip()
    # إزالة .0 من الأرقام المحولة من Excel
    if sid_str.endswith('.0'):
        sid_str = sid_str[:-2]
    return sid_str


def normalize_grade(grade: Any) -> Optional[float]:
    """تطبيع الدرجة"""
    if grade is None or grade == '':
        return None
    try:
        return float(grade)
    except (TypeError, ValueError):
        return None


def normalize_units(units: Any) -> int:
    """تطبيع عدد الوحدات"""
    if units is None or units == '':
        return 0
    try:
        return max(0, int(units))
    except (TypeError, ValueError):
        return 0


def sanitize_input(value: Any, max_length: int = 500) -> str:
    """تنظيف المدخلات من الأحرف الخطرة"""
    if value is None:
        return ""
    
    text = str(value).strip()
    
    # إزالة أحرف التحكم
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    
    # قص النص إذا كان طويلاً
    if len(text) > max_length:
        text = text[:max_length]
    
    return text


# ============================================
# Schema Validation
# ============================================

class Schema:
    """تعريف مخطط للتحقق من البيانات"""
    
    def __init__(self, fields: Dict[str, Dict]):
        """
        fields: قاموس يحتوي على تعريف كل حقل
        مثال:
        {
            'student_id': {'required': True, 'type': 'string', 'max_length': 50},
            'grade': {'required': False, 'type': 'number', 'min': 0, 'max': 100}
        }
        """
        self.fields = fields
    
    def validate(self, data: Dict) -> Dict:
        """
        التحقق من البيانات وإرجاع البيانات المنظفة
        Raises: ValidationError إذا فشل التحقق
        """
        cleaned = {}
        errors = []
        
        for field_name, rules in self.fields.items():
            value = data.get(field_name)
            
            # التحقق من الحقول المطلوبة
            if rules.get('required', False):
                if value is None or (isinstance(value, str) and not value.strip()):
                    errors.append(f"الحقل '{field_name}' مطلوب")
                    continue
            
            # إذا كانت القيمة فارغة وغير مطلوبة، نتخطاها
            if value is None or value == '':
                cleaned[field_name] = rules.get('default', None)
                continue
            
            # التحقق من النوع
            field_type = rules.get('type', 'string')
            
            if field_type == 'string':
                cleaned[field_name] = sanitize_input(value, rules.get('max_length', 500))
            
            elif field_type == 'number':
                try:
                    num = float(value)
                    if 'min' in rules and num < rules['min']:
                        errors.append(f"الحقل '{field_name}' يجب أن يكون أكبر من أو يساوي {rules['min']}")
                    elif 'max' in rules and num > rules['max']:
                        errors.append(f"الحقل '{field_name}' يجب أن يكون أصغر من أو يساوي {rules['max']}")
                    else:
                        cleaned[field_name] = num
                except (TypeError, ValueError):
                    errors.append(f"الحقل '{field_name}' يجب أن يكون رقماً")
            
            elif field_type == 'integer':
                try:
                    cleaned[field_name] = int(value)
                except (TypeError, ValueError):
                    errors.append(f"الحقل '{field_name}' يجب أن يكون عدداً صحيحاً")
            
            elif field_type == 'email':
                if not Validators.is_valid_email(value):
                    errors.append(f"الحقل '{field_name}' يجب أن يكون بريداً إلكترونياً صحيحاً")
                else:
                    cleaned[field_name] = str(value).strip()
            
            elif field_type == 'list':
                if not isinstance(value, list):
                    errors.append(f"الحقل '{field_name}' يجب أن يكون قائمة")
                else:
                    cleaned[field_name] = value
        
        if errors:
            raise ValidationError("; ".join(errors))
        
        return cleaned


# ============================================
# مخططات جاهزة للاستخدام
# ============================================

STUDENT_SCHEMA = Schema({
    'student_id': {'required': True, 'type': 'string', 'max_length': 50},
    'student_name': {'required': False, 'type': 'string', 'max_length': 200, 'default': ''},
    'email': {'required': False, 'type': 'email'},
    'phone': {'required': False, 'type': 'string', 'max_length': 20}
})

COURSE_SCHEMA = Schema({
    'course_name': {'required': True, 'type': 'string', 'max_length': 200},
    'course_code': {'required': False, 'type': 'string', 'max_length': 50, 'default': ''},
    'units': {'required': False, 'type': 'integer', 'default': 0}
})

GRADE_SCHEMA = Schema({
    'student_id': {'required': True, 'type': 'string', 'max_length': 50},
    'semester': {'required': True, 'type': 'string', 'max_length': 50},
    'course_name': {'required': True, 'type': 'string', 'max_length': 200},
    'grade': {'required': False, 'type': 'number', 'min': 0, 'max': 100}
})

SCHEDULE_SCHEMA = Schema({
    'course_name': {'required': True, 'type': 'string', 'max_length': 200},
    'day': {'required': True, 'type': 'string', 'max_length': 20},
    'time': {'required': True, 'type': 'string', 'max_length': 20},
    'room': {'required': False, 'type': 'string', 'max_length': 50, 'default': ''},
    'instructor': {'required': False, 'type': 'string', 'max_length': 100, 'default': ''},
    'semester': {'required': False, 'type': 'string', 'max_length': 50, 'default': ''}
})
