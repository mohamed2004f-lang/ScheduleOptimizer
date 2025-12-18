"""
اختبارات أساسية لخدمات التطبيق
"""
import pytest
import sys
import os

# إضافة مسار المشروع إلى Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.core.services import StudentService, CourseService, ScheduleService
from backend.core.exceptions import ValidationError, NotFoundError, DatabaseError


class TestStudentService:
    """اختبارات خدمة الطلاب"""
    
    def test_normalize_sid(self):
        """اختبار تطبيع معرّف الطالب"""
        assert StudentService.normalize_sid("123") == "123"
        assert StudentService.normalize_sid("  123  ") == "123"
        assert StudentService.normalize_sid(None) == ""
        assert StudentService.normalize_sid("") == ""
    
    def test_add_student_validation(self):
        """اختبار التحقق من صحة البيانات عند إضافة طالب"""
        with pytest.raises(ValidationError):
            StudentService.add_student("", "اسم الطالب")
        with pytest.raises(ValidationError):
            StudentService.add_student(None, "اسم الطالب")
    
    def test_get_all_students(self):
        """اختبار جلب جميع الطلاب"""
        # هذا الاختبار يتطلب قاعدة بيانات فعلية
        # يمكن تعطيله في بيئة الاختبار بدون قاعدة بيانات
        try:
            students = StudentService.get_all_students()
            assert isinstance(students, list)
        except DatabaseError:
            pytest.skip("قاعدة البيانات غير متاحة")


class TestCourseService:
    """اختبارات خدمة المقررات"""
    
    def test_add_course_validation(self):
        """اختبار التحقق من صحة البيانات عند إضافة مقرر"""
        with pytest.raises(ValidationError):
            CourseService.add_course("", "CODE", 3)
        with pytest.raises(ValidationError):
            CourseService.add_course(None, "CODE", 3)
        with pytest.raises(ValidationError):
            CourseService.add_course("   ", "CODE", 3)
    
    def test_get_all_courses(self):
        """اختبار جلب جميع المقررات"""
        try:
            courses = CourseService.get_all_courses()
            assert isinstance(courses, list)
        except DatabaseError:
            pytest.skip("قاعدة البيانات غير متاحة")


class TestScheduleService:
    """اختبارات خدمة الجدول الدراسي"""
    
    def test_add_schedule_row_validation(self):
        """اختبار التحقق من صحة البيانات عند إضافة صف للجدول"""
        with pytest.raises(ValidationError):
            ScheduleService.add_schedule_row("", "السبت", "09:00")
        with pytest.raises(ValidationError):
            ScheduleService.add_schedule_row("مقرر", "", "09:00")
        with pytest.raises(ValidationError):
            ScheduleService.add_schedule_row("مقرر", "السبت", "")
    
    def test_delete_schedule_row_validation(self):
        """اختبار التحقق من صحة البيانات عند حذف صف"""
        with pytest.raises(ValidationError):
            ScheduleService.delete_schedule_row(None)
        with pytest.raises(ValidationError):
            ScheduleService.delete_schedule_row(0)

