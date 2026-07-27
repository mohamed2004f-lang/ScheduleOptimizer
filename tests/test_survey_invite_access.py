"""صلاحيات دعوات الاستبيانات الخارجية وعرض النتائج حسب القسم."""

from __future__ import annotations

from backend.core.auth import (
    SURVEY_INVITE_MANAGE_ROLES,
    can_manage_survey_invites,
    can_view_survey_results,
    compute_capabilities,
)
from backend.services.survey_external_analytics import (
    aggregate_external_template_scoped,
    filter_external_rows_by_department,
)


def test_invite_manage_roles_are_dean_and_main_admin_only():
    assert SURVEY_INVITE_MANAGE_ROLES == {"admin_main", "system_admin", "college_dean"}


def test_compute_capabilities_invite_manage_for_dean():
    caps = compute_capabilities("college_dean", 0, "dean")
    assert caps.get("can_manage_survey_invites") is True
    assert caps.get("nav_surveys_invites") is True
    assert caps.get("nav_surveys_results") is True


def test_compute_capabilities_hod_results_without_invites():
    caps = compute_capabilities("head_of_department", 0, "head")
    assert caps.get("nav_surveys_results") is True
    assert caps.get("can_manage_survey_invites") is False
    assert caps.get("nav_surveys_invites") is False


def test_compute_capabilities_vice_dean_results_without_invites():
    from backend.core.permissions import compute_academic_vice_dean_capabilities

    caps = compute_academic_vice_dean_capabilities("vice_dean", 0)
    assert caps.get("nav_surveys_results") is True
    # قد تُفرض لاحقاً عبر resolve؛ الأساس بلا إدارة دعوات
    assert caps.get("can_manage_survey_invites") in (None, False)


def test_can_manage_survey_invites_session(app):
    with app.test_request_context():
        from flask import session

        session["user_role"] = "head_of_department"
        assert can_manage_survey_invites() is False
        session["user_role"] = "college_dean"
        assert can_manage_survey_invites() is True
        session["user_role"] = "admin_main"
        assert can_manage_survey_invites() is True


def test_can_view_results_includes_quality_lead(app):
    with app.test_request_context():
        from flask import session

        session["user_role"] = "staff"
        session["is_college_quality_lead"] = 0
        assert can_view_survey_results() is False
        session["is_college_quality_lead"] = 1
        assert can_view_survey_results() is True


def test_filter_external_rows_by_department_alumni():
    rows = [
        {"id": 1, "profile": {"department_id": 10}},
        {"id": 2, "profile": {"department_id": 20}},
        {"id": 3, "profile": {"department_id": 10}},
    ]
    filtered = filter_external_rows_by_department("alumni", rows, 10)
    assert [r["id"] for r in filtered] == [1, 3]


def test_aggregate_external_scoped_empty(db_conn):
    agg = aggregate_external_template_scoped(
        db_conn, "alumni", cycle_label="no-such-cycle", department_id=1
    )
    assert agg.get("response_count") == 0
    assert agg.get("aggregated") is False
