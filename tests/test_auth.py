"""
اختبارات نظام المصادقة
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.core.auth import (
    hash_password,
    verify_password,
    compute_capabilities,
    is_supervisor_effective_session,
    _normalize_role,
)


class TestAuth:
    """اختبارات المصادقة"""

    def test_normalize_role_head_case_insensitive(self):
        assert _normalize_role("head_of_department") == "head_of_department"
        assert _normalize_role("Head_of_department") == "head_of_department"
        assert _normalize_role("HEAD_OF_DEPARTMENT") == "head_of_department"
        assert _normalize_role("Instructor") == "instructor"
        assert _normalize_role("head") == "head_of_department"
        assert _normalize_role("HOD") == "head_of_department"
        assert _normalize_role("head-of-department") == "head_of_department"
        assert _normalize_role("head of department") == "head_of_department"
        assert _normalize_role("رئيس قسم") == "head_of_department"

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
        assert caps.get("nav_course_closure_reports") is True
        assert caps.get("nav_faculty_scorecards") is True
        assert caps.get("nav_faculty_final_dossier") is True
        assert caps.get("is_instructor_or_supervisor_nav") is False

    def test_head_of_department_with_supervisor_flag_not_instructor_nav(self):
        """حتى مع is_supervisor=1 في DB لا يُعامل رئيس القسم كأستاذ (شؤون الطلبة تبقى ظاهرة)."""
        caps = compute_capabilities("head_of_department", 1)
        assert caps.get("is_instructor_or_supervisor_nav") is False
        assert caps.get("nav_student_affairs_attendance_only") is False

    def test_head_triple_active_modes(self):
        """رئيس القسم: أوضاع head / instructor / supervisor."""
        c_head = compute_capabilities("head_of_department", 0, "head")
        assert c_head.get("active_mode_switch_profile") == "triple"
        assert c_head.get("can_switch_active_mode") is True
        assert c_head.get("can_manage_schedule_edit") is True
        c_ins = compute_capabilities("head_of_department", 0, "instructor")
        assert c_ins.get("nav_student_affairs_attendance_only") is True
        assert c_ins.get("can_manage_schedule_edit") is False
        assert c_ins.get("is_instructor_or_supervisor_nav") is True
        c_sup = compute_capabilities("head_of_department", 0, "supervisor")
        assert c_sup.get("nav_transcript_nav") is True
        assert c_sup.get("is_supervisor_effective") is True

    def test_compute_capabilities_student(self):
        caps = compute_capabilities("student", 0)
        assert caps["is_student"] is True
        assert caps["can_manage_courses_edit"] is False

    def test_compute_capabilities_instructor_my_courses_nav(self):
        caps = compute_capabilities("instructor", 0)
        assert caps.get("nav_my_assigned_courses") is True
        assert caps.get("nav_grade_drafts") is False
        assert caps.get("nav_student_affairs_attendance_only") is True
        assert caps.get("nav_transcript_nav") is False
        assert caps.get("nav_faculty_scorecards") is True
        assert caps.get("nav_course_closure_reports") is False
        assert caps.get("nav_faculty_final_dossier") is False
        caps2 = compute_capabilities("admin_main", 0)
        assert caps2.get("nav_my_assigned_courses") is False
        assert caps2.get("nav_course_closure_reports") is True
        assert caps2.get("nav_faculty_scorecards") is True
        assert caps2.get("nav_faculty_final_dossier") is True

    def test_compute_capabilities_instructor_as_supervisor_sees_transcript_nav(self):
        caps = compute_capabilities("instructor", 1, "supervisor")
        assert caps.get("nav_student_affairs_attendance_only") is False
        assert caps.get("nav_transcript_nav") is True
        assert caps.get("can_switch_active_mode") is True
        assert caps.get("active_mode_switch_profile") == "dual"

    def test_compute_capabilities_instructor_dual_teaching_mode(self):
        caps = compute_capabilities("instructor", 1, "instructor")
        assert caps.get("nav_student_affairs_attendance_only") is True
        assert caps.get("nav_transcript_nav") is False

    def test_is_supervisor_effective_session(self):
        assert is_supervisor_effective_session("instructor", 1, "supervisor") is True
        assert is_supervisor_effective_session("instructor", 1, "instructor") is False
        assert is_supervisor_effective_session("instructor", 0, "supervisor") is False
        assert is_supervisor_effective_session("supervisor", 0, None) is True
        assert is_supervisor_effective_session("head_of_department", 0, "supervisor") is True
        assert is_supervisor_effective_session("head_of_department", 0, "head") is False
        assert is_supervisor_effective_session("head_of_department", 0, "instructor") is False
