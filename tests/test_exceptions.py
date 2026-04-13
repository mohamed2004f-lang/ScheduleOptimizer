"""
اختبارات نظام معالجة الأخطاء
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.core.exceptions import (
    AppException, ValidationError, NotFoundError, 
    DatabaseError, UnauthorizedError, ForbiddenError
)


class TestExceptions:
    """اختبارات الاستثناءات"""
    
    def test_app_exception_default(self):
        """اختبار الاستثناء الأساسي بالقيم الافتراضية"""
        exc = AppException()
        assert exc.status_code == 500
        assert exc.message == "حدث خطأ غير متوقع"
        assert exc.to_dict() == {
            'status': 'error',
            'message': 'حدث خطأ غير متوقع',
            'code': 'INTERNAL_ERROR',
        }
    
    def test_app_exception_custom(self):
        """اختبار الاستثناء الأساسي بقيم مخصصة"""
        exc = AppException("خطأ مخصص", status_code=400, payload={'field': 'value'})
        assert exc.status_code == 400
        assert exc.message == "خطأ مخصص"
        assert exc.to_dict() == {
            'status': 'error',
            'message': 'خطأ مخصص',
            'code': 'INTERNAL_ERROR',
            'field': 'value',
        }
    
    def test_validation_error(self):
        """اختبار خطأ التحقق من الصحة"""
        exc = ValidationError("بيانات غير صحيحة")
        assert exc.status_code == 400
        assert exc.message == "بيانات غير صحيحة"
    
    def test_not_found_error(self):
        """اختبار خطأ المورد غير موجود"""
        exc = NotFoundError("الطالب غير موجود")
        assert exc.status_code == 404
        assert exc.message == "الطالب غير موجود"
    
    def test_database_error(self):
        """اختبار خطأ قاعدة البيانات"""
        exc = DatabaseError("فشل الاتصال بقاعدة البيانات")
        assert exc.status_code == 500
        assert exc.message == "فشل الاتصال بقاعدة البيانات"
    
    def test_unauthorized_error(self):
        """اختبار خطأ عدم التصريح"""
        exc = UnauthorizedError("يجب تسجيل الدخول")
        assert exc.status_code == 401
        assert exc.message == "يجب تسجيل الدخول"
    
    def test_forbidden_error(self):
        """اختبار خطأ الممنوع"""
        exc = ForbiddenError("غير مصرح بالوصول")
        assert exc.status_code == 403
        assert exc.message == "غير مصرح بالوصول"

