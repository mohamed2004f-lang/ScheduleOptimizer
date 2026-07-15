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
    assert "applyQualityNavTier" in NAV
    assert "applyRoleDropdownOrders" in NAV
    assert "nav-staff-expanded" in NAV


def test_dean_has_admin_settings_cap():
    caps = compute_capabilities("college_dean", 0, "dean")
    assert caps.get("nav_admin_settings") is True
    assert caps.get("nav_users_admin") is True


def test_hod_head_has_dept_settings_cap():
    caps = compute_capabilities("head_of_department", 0, "head")
    assert caps.get("nav_admin_settings") is True
    assert caps.get("nav_users_admin") is False


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
