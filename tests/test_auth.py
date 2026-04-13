"""
اختبارات نظام المصادقة
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.core.auth import hash_password, verify_password


class TestAuth:
    """اختبارات المصادقة"""
    
    def test_hash_password(self):
        """اختبار تشفير كلمة المرور"""
        password = "test123"
        hashed = hash_password(password)
        
        # يجب أن يكون التشفير مختلفاً عن النص الأصلي
        assert hashed != password

        # Werkzeug يولّد salt عشوائياً لكل استدعاء — الهاش يختلف لكن التحقق ينجح
        hashed_again = hash_password(password)
        assert hashed_again != password
        assert verify_password(password, hashed)
        assert verify_password(password, hashed_again)
    
    def test_verify_password(self):
        """اختبار التحقق من كلمة المرور"""
        password = "test123"
        hashed = hash_password(password)
        
        # يجب أن يتحقق من كلمة المرور الصحيحة
        assert verify_password(password, hashed) == True
        
        # يجب أن يرفض كلمة المرور الخاطئة
        assert verify_password("wrong", hashed) == False
        assert verify_password("test124", hashed) == False

