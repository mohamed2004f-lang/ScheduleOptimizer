"""اختبارات بوابة ضمان الجودة للأستاذ."""

import pytest

from backend.core.auth import compute_capabilities
from backend.services.instructor_portal import (
    build_instructor_quality_context,
)


class TestInstructorQualityCaps:
    def test_instructor_has_quality_hub_cap(self):
        caps = compute_capabilities("instructor", 0)
        assert caps.get("nav_instructor_quality_hub") is True
        assert caps.get("nav_student_academic_identity") is False

    def test_student_has_identity_not_instructor_hub(self):
        caps = compute_capabilities("student", 0)
        assert caps.get("nav_student_academic_identity") is True
        assert caps.get("nav_instructor_quality_hub") is False

    def test_hod_instructor_mode_quality_hub(self):
        caps = compute_capabilities("head_of_department", 0, "instructor")
        assert caps.get("nav_instructor_quality_hub") is True

    def test_hod_head_mode_no_instructor_hub(self):
        caps = compute_capabilities("head_of_department", 0, "head")
        assert caps.get("nav_instructor_quality_hub") is False


class TestInstructorQualityPages:
    def test_quality_hub_requires_auth(self, app):
        with app.test_client() as c:
            resp = c.get("/academic_quality/instructor/quality-hub", follow_redirects=False)
            assert resp.status_code in (302, 301)

    def test_quality_hub_instructor_ok(self, instructor_auth_client):
        resp = instructor_auth_client.get("/academic_quality/instructor/quality-hub")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True) or ""
        assert "instructor_quality_hub" in html or "ضمان الجودة" in html
        assert "navInsQualityHub" in html or "quality-hub" in html

    def test_quality_hub_student_blocked(self, student_auth_client):
        resp = student_auth_client.get("/academic_quality/instructor/quality-hub", follow_redirects=False)
        assert resp.status_code in (302, 301)
        assert "my_portal" in resp.headers.get("Location", "")

    def test_quality_context_api_instructor(self, instructor_auth_client):
        resp = instructor_auth_client.get(
            "/instructors/quality_context",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "ok"
        assert "college" in data
        assert "surveys" in data
        assert "program" not in data

    def test_quality_context_api_student_forbidden(self, student_auth_client):
        resp = student_auth_client.get(
            "/instructors/quality_context",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 403

    def test_v1_quality_context_api(self, instructor_auth_client):
        resp = instructor_auth_client.get(
            "/api/v1/instructors/me/quality_context",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("success") is True
        assert "college" in (data.get("data") or {})

    def test_student_identity_api_forbidden_for_instructor(self, instructor_auth_client):
        resp = instructor_auth_client.get(
            "/students/identity_context",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 403

    def test_instructor_blocked_from_student_portal(self, instructor_auth_client):
        resp = instructor_auth_client.get("/my_portal", follow_redirects=False)
        assert resp.status_code in (302, 301, 403)
        if resp.status_code in (302, 301):
            assert "my_courses" in resp.headers.get("Location", "")

    def test_instructor_my_courses_ok(self, instructor_auth_client):
        resp = instructor_auth_client.get("/my_courses")
        assert resp.status_code == 200

    def test_instructor_nav_shell_on_quality_hub(self, instructor_auth_client):
        resp = instructor_auth_client.get("/academic_quality/instructor/quality-hub")
        html = resp.get_data(as_text=True) or ""
        assert "navInsQualityHub" in html
        assert "nav-shell-instructor" in html or "navShellInstructorCritical" in html


class TestInstructorQualityContextBuilder:
    def test_build_context_shape(self, app, db_conn):
        with app.test_request_context():
            ctx = build_instructor_quality_context(
                db_conn,
                role="instructor",
                session_data={
                    "user": "inst-test",
                    "user_role": "instructor",
                    "instructor_id": 1,
                    "is_supervisor": 0,
                },
                active_mode="instructor",
            )
        assert ctx.get("college")
        assert "surveys" in ctx
        assert ctx["surveys"].get("pending_count") is not None
        assert "program" not in ctx
