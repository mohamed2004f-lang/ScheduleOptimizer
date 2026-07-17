# -*- coding: utf-8 -*-
"""Smoke: هيكل القائمة الرئيسية + breadcrumb الجودة بعد إعادة ترتيب IA."""
from pathlib import Path

from backend.core.auth import compute_capabilities

ROOT = Path(__file__).resolve().parents[1]
NAV = (ROOT / "frontend" / "templates" / "base_nav.html").read_text(encoding="utf-8")
BC = (ROOT / "frontend" / "templates" / "partials" / "quality_breadcrumb.html").read_text(
    encoding="utf-8"
)


def test_nav_core_ids_preserved():
    for nav_id in (
        "navDashboard",
        "navStudentAffairsWrap",
        "navPlanningMenuWrap",
        "navAcademicRecordsMenuWrap",
        "navCatalogWrap",
        "navFacultySupervisionWrap",
        "navQualityAccreditationWrap",
        "navAdminSettingsWrap",
        "navStaffCompactMoreWrap",
        "navTermClosure",
        "navHodCourseDeliveryTop",
        "navDeanFinalBatches",
        "navHodFinalBatch",
        "academicRecordsMenuList",
        "studentAffairsMenuList",
        "adminSettingsMenuList",
    ):
        assert f'id="{nav_id}"' in NAV, nav_id


def test_nav_short_labels_present():
    assert 'class="nav-label-short"' in NAV
    assert 'class="nav-label-full"' in NAV
    assert "الجودة" in NAV
    assert "المقررات" in NAV


def test_nav_role_secondary_and_expanded_order_config():
    assert "STAFF_NAV_SECONDARY_BY_ROLE" in NAV
    assert "QUALITY_PRIMARY_ROLES" in NAV
    assert "COMPACT_PRIMARY_ORDER" in NAV
    assert "applyQualityNavTier" in NAV
    assert "applyRoleDropdownOrders" in NAV
    assert "applyCompactNavOrder" in NAV
    assert "nav-staff-expanded" in NAV
    # رئيس القسم: الجودة primary مثل القيادات + اعتماد القسم في الترتيب
    assert "'head_of_department'" in NAV
    assert "navHodCourseDeliveryWrap" in NAV
    # الجودة لم تعد ضمن secondary لرئيس القسم (خرجت من «المزيد»)
    hod_block_start = NAV.find("head_of_department: [")
    assert hod_block_start > 0
    # أول ظهور بعد secondary roles — تحقق من COMPACT و EXPANDED
    assert "navHodCourseDeliveryWrap" in NAV[hod_block_start : hod_block_start + 2500]


def test_hod_head_ops_caps_and_quality():
    caps = compute_capabilities("head_of_department", 0, "head")
    assert caps.get("nav_staff_operations_menu") is True
    assert caps.get("nav_term_closure") is True
    assert caps.get("nav_surveys_results") is True
    assert caps.get("nav_admin_settings") is True
    assert caps.get("nav_users_admin") is False
    assert caps.get("nav_dashboard") is True


def test_hod_instructor_mode_not_staff_ops():
    caps = compute_capabilities("head_of_department", 0, "instructor")
    assert caps.get("nav_staff_operations_menu") is False
    assert caps.get("nav_instructor_portal_menu") is True


def test_dean_has_admin_settings_cap():
    caps = compute_capabilities("college_dean", 0, "dean")
    assert caps.get("nav_admin_settings") is True
    assert caps.get("nav_users_admin") is True


def test_vice_dean_no_admin_settings():
    caps = compute_capabilities("academic_vice_dean", 0, "vice_dean")
    assert caps.get("nav_admin_settings") is False
    assert caps.get("nav_term_closure") is True


def test_quality_breadcrumb_partial():
    assert "so-quality-breadcrumb" in BC
    assert "/academic_quality/dashboard" in BC
    assert "qa_crumb_hub" in BC


def test_key_quality_pages_include_breadcrumb():
    pages = [
        "term_closure.html",
        "survey_results.html",
        "quality_assistant.html",
        "quality_glossary.html",
        "department_archive.html",
        "accreditation_compliance_map.html",
        "college_profile.html",
    ]
    for name in pages:
        text = (ROOT / "frontend" / "templates" / name).read_text(encoding="utf-8")
        assert "partials/quality_breadcrumb.html" in text, name
