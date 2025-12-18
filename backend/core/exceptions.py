"""
نظام معالجة الأخطاء الموحد
يوفر استثناءات مخصصة ومعالجات أخطاء لـ Flask
"""
from flask import jsonify
import logging
import traceback

logger = logging.getLogger(__name__)


# ============================================
# الاستثناءات المخصصة
# ============================================

class AppException(Exception):
    """الاستثناء الأساسي للتطبيق"""
    status_code = 500
    message = "حدث خطأ غير متوقع"
    code = "INTERNAL_ERROR"

    def __init__(self, message=None, status_code=None, code=None, payload=None):
        super().__init__()
        if message:
            self.message = message
        if status_code:
            self.status_code = status_code
        if code:
            self.code = code
        self.payload = payload

    def to_dict(self):
        rv = {
            'status': 'error',
            'message': self.message,
            'code': self.code
        }
        if self.payload:
            rv.update(self.payload)
        return rv


class ValidationError(AppException):
    """خطأ في التحقق من صحة البيانات"""
    status_code = 400
    message = "بيانات غير صحيحة"
    code = "VALIDATION_ERROR"


class NotFoundError(AppException):
    """المورد غير موجود"""
    status_code = 404
    message = "المورد المطلوب غير موجود"
    code = "NOT_FOUND"


class DatabaseError(AppException):
    """خطأ في قاعدة البيانات"""
    status_code = 500
    message = "خطأ في قاعدة البيانات"
    code = "DATABASE_ERROR"


class UnauthorizedError(AppException):
    """غير مصرح بالوصول"""
    status_code = 401
    message = "غير مصرح بالوصول"
    code = "UNAUTHORIZED"


class ForbiddenError(AppException):
    """ممنوع الوصول"""
    status_code = 403
    message = "ممنوع الوصول"
    code = "FORBIDDEN"


class ConflictError(AppException):
    """تعارض في البيانات"""
    status_code = 409
    message = "تعارض في البيانات"
    code = "CONFLICT"


class RateLimitError(AppException):
    """تجاوز حد الطلبات"""
    status_code = 429
    message = "تم تجاوز الحد المسموح من الطلبات"
    code = "RATE_LIMIT_EXCEEDED"


class ServiceUnavailableError(AppException):
    """الخدمة غير متاحة"""
    status_code = 503
    message = "الخدمة غير متاحة حالياً"
    code = "SERVICE_UNAVAILABLE"


# ============================================
# معالجات الأخطاء
# ============================================

def register_error_handlers(app):
    """تسجيل معالجات الأخطاء في Flask app"""
    
    @app.errorhandler(AppException)
    def handle_app_exception(e):
        """معالجة استثناءات التطبيق"""
        logger.error(f"AppException [{e.code}]: {e.message}")
        response = jsonify(e.to_dict())
        response.status_code = e.status_code
        return response

    @app.errorhandler(400)
    def handle_bad_request(e):
        """معالجة طلب غير صحيح"""
        return jsonify({
            'status': 'error',
            'message': 'طلب غير صحيح',
            'code': 'BAD_REQUEST'
        }), 400

    @app.errorhandler(401)
    def handle_unauthorized(e):
        """معالجة عدم المصادقة"""
        return jsonify({
            'status': 'error',
            'message': 'يجب تسجيل الدخول للوصول إلى هذه الصفحة',
            'code': 'UNAUTHORIZED'
        }), 401

    @app.errorhandler(403)
    def handle_forbidden(e):
        """معالجة عدم الصلاحية"""
        return jsonify({
            'status': 'error',
            'message': 'ليس لديك صلاحية للوصول إلى هذا المورد',
            'code': 'FORBIDDEN'
        }), 403

    @app.errorhandler(404)
    def handle_not_found(e):
        """معالجة عدم وجود الصفحة"""
        return jsonify({
            'status': 'error',
            'message': 'الصفحة المطلوبة غير موجودة',
            'code': 'NOT_FOUND'
        }), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        """معالجة طريقة غير مسموحة"""
        return jsonify({
            'status': 'error',
            'message': 'طريقة الطلب غير مسموحة',
            'code': 'METHOD_NOT_ALLOWED'
        }), 405

    @app.errorhandler(429)
    def handle_rate_limit(e):
        """معالجة تجاوز حد الطلبات"""
        return jsonify({
            'status': 'error',
            'message': 'تم تجاوز الحد المسموح من الطلبات. يرجى المحاولة لاحقاً.',
            'code': 'RATE_LIMIT_EXCEEDED'
        }), 429

    @app.errorhandler(500)
    def handle_internal_error(e):
        """معالجة خطأ داخلي"""
        logger.error(f"Internal server error: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'status': 'error',
            'message': 'حدث خطأ داخلي في الخادم',
            'code': 'INTERNAL_ERROR'
        }), 500

    @app.errorhandler(503)
    def handle_service_unavailable(e):
        """معالجة عدم توفر الخدمة"""
        return jsonify({
            'status': 'error',
            'message': 'الخدمة غير متاحة حالياً',
            'code': 'SERVICE_UNAVAILABLE'
        }), 503

    @app.errorhandler(Exception)
    def handle_generic_exception(e):
        """معالجة الاستثناءات العامة"""
        logger.error(f"Unhandled exception: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'status': 'error',
            'message': 'حدث خطأ غير متوقع',
            'code': 'UNKNOWN_ERROR'
        }), 500

    logger.info("Error handlers registered")


# ============================================
# دوال مساعدة
# ============================================

def error_response(message: str, code: str = "ERROR", status_code: int = 400, **kwargs):
    """إنشاء استجابة خطأ موحدة"""
    response = {
        'status': 'error',
        'message': message,
        'code': code
    }
    response.update(kwargs)
    return jsonify(response), status_code


def success_response(message: str = "تمت العملية بنجاح", **kwargs):
    """إنشاء استجابة نجاح موحدة"""
    response = {
        'status': 'ok',
        'message': message
    }
    response.update(kwargs)
    return jsonify(response), 200
