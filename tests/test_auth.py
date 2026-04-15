"""
اختبارات نظام المصادقة
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.core.auth import hash_password, verify_password, compute_capabilities


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

    def test_compute_capabilities_head_of_department(self):
        caps = compute_capabilities("head_of_department", 0)
        assert caps["v"] == 1
        assert caps["can_manage_schedule_edit"] is True
        assert caps["nav_users_admin"] is False

    def test_compute_capabilities_student(self):
        caps = compute_capabilities("student", 0)
        assert caps["is_student"] is True
        assert caps["can_manage_courses_edit"] is False

    def test_compute_capabilities_instructor_my_courses_nav(self):
        caps = compute_capabilities("instructor", 0)
        assert caps.get("nav_my_assigned_courses") is True
        caps2 = compute_capabilities("admin_main", 0)
        assert caps2.get("nav_my_assigned_courses") is False
