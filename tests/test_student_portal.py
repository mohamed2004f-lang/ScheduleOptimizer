"""اختبارات بوابة الطالب (المراحل 1–4)."""

import pytest


class TestStudentPortalPages:
    def test_my_portal_requires_auth(self, app):
        with app.test_client() as c:
            resp = c.get("/my_portal", follow_redirects=False)
            assert resp.status_code in (302, 301)
            assert "/login" in resp.headers.get("Location", "")

    def test_my_portal_student_ok(self, student_auth_client):
        resp = student_auth_client.get("/my_portal")
        assert resp.status_code == 200
        assert "student_portal" in (resp.get_data(as_text=True) or "").lower() or "بواب" in resp.get_data(as_text=True)

    def test_student_view_redirects_to_portal(self, student_auth_client):
        resp = student_auth_client.get("/student_view", follow_redirects=False)
        assert resp.status_code in (302, 301)
        assert "my_portal" in resp.headers.get("Location", "")

    def test_transcript_page_redirects_student(self, student_auth_client):
        resp = student_auth_client.get("/transcript_page", follow_redirects=False)
        assert resp.status_code in (302, 301)
        assert "my_transcript" in resp.headers.get("Location", "")

    def test_my_transcript_student_ok(self, student_auth_client):
        resp = student_auth_client.get("/my_transcript")
        assert resp.status_code == 200

    def test_academic_identity_page(self, student_auth_client):
        resp = student_auth_client.get("/academic_quality/student/identity")
        assert resp.status_code == 200

    def test_academic_progress_page(self, student_auth_client):
        resp = student_auth_client.get("/academic_quality/student/progress")
        assert resp.status_code == 200


class TestStudentPortalAPI:
    def test_portal_summary(self, student_auth_client):
        resp = student_auth_client.get(
            "/students/portal_summary",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "ok"
        assert "student_id" in data
        assert "action_items" in data

    def test_student_me(self, student_auth_client):
        resp = student_auth_client.get(
            "/students/me",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "ok"
        assert data.get("student_id")

    def test_identity_context(self, student_auth_client):
        resp = student_auth_client.get(
            "/students/identity_context",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "ok"
        assert "college" in data

    def test_academic_progress_api(self, student_auth_client):
        resp = student_auth_client.get(
            "/students/academic_progress",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "ok"

    def test_v1_portal_summary(self, student_auth_client):
        resp = student_auth_client.get(
            "/api/v1/students/me/portal_summary",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("success") is True
        assert "data" in data

    def test_portal_summary_forbidden_for_admin(self, auth_client):
        resp = auth_client.get(
            "/students/portal_summary",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 403
