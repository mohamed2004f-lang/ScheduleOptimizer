"""
نظام معالجة الأخطاء الموحد
"""
from flask import jsonify
import logging

logger = logging.getLogger(__name__)


class AppException(Exception):
    """الاستثناء الأساسي للتطبيق"""
    status_code = 500
    message = "حدث خطأ غير متوقع"

    def __init__(self, message=None, status_code=None, payload=None):
        super().__init__()
        if message:
            self.message = message
        if status_code:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = {
            'status': 'error',
            'message': self.message
        }
        if self.payload:
            rv.update(self.payload)
        return rv


class ValidationError(AppException):
    """خطأ في التحقق من صحة البيانات"""
    status_code = 400
    message = "بيانات غير صحيحة"


class NotFoundError(AppException):
    """المورد غير موجود"""
    status_code = 404
    message = "المورد المطلوب غير موجود"


class DatabaseError(AppException):
    """خطأ في قاعدة البيانات"""
    status_code = 500
    message = "خطأ في قاعدة البيانات"


class UnauthorizedError(AppException):
    """غير مصرح بالوصول"""
    status_code = 401
    message = "غير مصرح بالوصول"


class ForbiddenError(AppException):
    """ممنوع الوصول"""
    status_code = 403
    message = "ممنوع الوصول"


def register_error_handlers(app):
    """تسجيل معالجات الأخطاء في Flask app"""
    
    @app.errorhandler(AppException)
    def handle_app_exception(e):
        logger.error(f"AppException: {e.message}", exc_info=True)
        response = jsonify(e.to_dict())
        response.status_code = e.status_code
        return response

    @app.errorhandler(404)
    def handle_not_found(e):
        return jsonify({
            'status': 'error',
            'message': 'الصفحة المطلوبة غير موجودة'
        }), 404

    @app.errorhandler(500)
    def handle_internal_error(e):
        logger.error("Internal server error", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'حدث خطأ داخلي في الخادم'
        }), 500

    @app.errorhandler(Exception)
    def handle_generic_exception(e):
        logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'حدث خطأ غير متوقع'
        }), 500

