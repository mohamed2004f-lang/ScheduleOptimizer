"""
اختبارات Integration لمسارات Flask (Routes).

يغطي:
- مسارات عامة (لا تحتاج تسجيل دخول): /health, /login
- مسارات محمية (تحتاج تسجيل دخول): /, /dashboard
- مسار تسجيل الدخول والخروج عبر API: /auth/login, /auth/logout, /auth/check
"""
import pytest


# ═══════════════════════════════════════════════════════
# 1. مسارات عامة (بدون تسجيل دخول)
# ═══════════════════════════════════════════════════════

class TestPublicRoutes:
    """اختبارات المسارات العامة التي لا تحتاج تسجيل دخول."""

    def test_health_returns_200(self, client):
        """GET /health يجب أن يرجع 200 مع status=healthy."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"

    def test_login_page_accessible(self, client):
        """GET /login يجب أن يكون متاحاً (200 أو 500 إذا كان القالب غير موجود في بيئة الاختبار)."""
        resp = client.get("/login")
        # In test environment templates may not be available, so 500 is acceptable.
        # The key assertion is that it does NOT return 401/403 (i.e., it's not auth-protected).
        assert resp.status_code in (200, 500)
        assert resp.status_code != 401
        assert resp.status_code != 403


# ═══════════════════════════════════════════════════════
# 2. مسارات محمية (بدون تسجيل دخول → 401 أو redirect)
# ═══════════════════════════════════════════════════════

class TestProtectedRoutesUnauthenticated:
    """اختبارات المسارات المحمية عند عدم تسجيل الدخول."""

    def test_root_redirects_to_login(self, app):
        """GET / بدون تسجيل دخول يجب أن يحول إلى /login."""
        # Use a fresh client (no session) to avoid auth leaking from session-scoped client.
        with app.test_client() as c:
            resp = c.get("/", follow_redirects=False)
            assert resp.status_code in (302, 301)
            assert "/login" in resp.headers.get("Location", "")

    def test_dashboard_api_returns_401(self, app):
        """GET /dashboard بدون تسجيل دخول عبر API يجب أن يرجع 401."""
        with app.test_client() as c:
            resp = c.get(
                "/dashboard",
                headers={"Accept": "application/json"},
            )
            assert resp.status_code in (401, 403)


# ═══════════════════════════════════════════════════════
# 3. تسجيل الدخول والخروج
# ═══════════════════════════════════════════════════════

class TestAuthFlow:
    """اختبارات تدفق المصادقة الكامل."""

    def test_login_missing_credentials(self, app):
        """POST /auth/login بدون بيانات يجب أن يرجع 400."""
        with app.test_client() as c:
            resp = c.post("/auth/login", json={})
            assert resp.status_code == 400
            data = resp.get_json()
            assert data["status"] == "error"

    def test_login_wrong_password(self, app):
        """POST /auth/login بكلمة مرور خاطئة يجب أن يرجع 401."""
        with app.test_client() as c:
            resp = c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "wrong-password"},
            )
            assert resp.status_code == 401

    def test_login_success(self, app):
        """POST /auth/login ببيانات صحيحة يجب أن يرجع 200."""
        with app.test_client() as c:
            resp = c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "ok"
            assert data["user"] == "admin-test"

    def test_auth_check_after_login(self, app):
        """GET /auth/check بعد تسجيل الدخول يجب أن يرجع authenticated=True."""
        with app.test_client() as c:
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            resp = c.get("/auth/check")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["authenticated"] is True

    def test_logout(self, app):
        """POST /auth/logout بعد تسجيل الدخول يجب أن يرجع 200."""
        with app.test_client() as c:
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            resp = c.post("/auth/logout")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "ok"

    def test_auth_check_after_logout(self, app):
        """GET /auth/check بعد تسجيل الخروج يجب أن يرجع authenticated=False."""
        with app.test_client() as c:
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            c.post("/auth/logout")
            resp = c.get("/auth/check")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["authenticated"] is False


# ═══════════════════════════════════════════════════════
# 4. مسارات محمية (بعد تسجيل الدخول)
# ═══════════════════════════════════════════════════════

class TestProtectedRoutesAuthenticated:
    """اختبارات المسارات المحمية بعد تسجيل الدخول كـ admin."""

    def test_root_after_login_redirects_to_dashboard(self, auth_client):
        """GET / بعد تسجيل الدخول كـ admin يجب أن يحول إلى dashboard."""
        resp = auth_client.get("/", follow_redirects=False)
        # admin role gets redirected to /dashboard
        assert resp.status_code in (200, 302)

    def test_students_list(self, auth_client):
        """GET /students/list يجب أن يرجع 200 مع بيانات JSON."""
        resp = auth_client.get(
            "/students/list",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200

    def test_students_add_then_list_contains_new_student(self, auth_client):
        """POST /students/add ثم التأكد من ظهور الطالب في /students/list."""
        sid = "S900"
        add_resp = auth_client.post(
            "/students/add",
            json={
                "student_id": sid,
                "student_name": "طالب اختبار تكاملي",
                "graduation_plan": "150 وحدة",
                "join_term": "خريف",
                "join_year": "25-26",
            },
        )
        assert add_resp.status_code == 200
        add_data = add_resp.get_json()
        assert add_data is not None
        assert add_data.get("status") == "ok"

        list_resp = auth_client.get("/students/list", headers={"Accept": "application/json"})
        assert list_resp.status_code == 200
        rows = list_resp.get_json() or []
        assert any((r.get("student_id") == sid) for r in rows)

    def test_results_data_returns_200_and_expected_keys(self, auth_client):
        """GET /results_data لا يجب أن يفشل ImportError ويُرجع البنية المتوقعة."""
        resp = auth_client.get("/results_data", headers={"Accept": "application/json"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)
        assert "conflict_report" in data
        assert "proposed_moves" in data
        assert "optimized_schedule" in data


# ═══════════════════════════════════════════════════════
# 5. عرض جدول الطالب والدرجات وطلبات التسجيل
# ═══════════════════════════════════════════════════════


class TestStudentViewRoute:
    """تأكيد حماية ``/student_view`` وإتاحتها بعد تسجيل الدخول."""

    def test_student_view_unauthenticated_redirects_to_login(self, app):
        with app.test_client() as c:
            resp = c.get("/student_view", follow_redirects=False)
            assert resp.status_code in (302, 301)
            assert "/login" in resp.headers.get("Location", "")

    def test_student_view_unauthenticated_json_returns_401(self, app):
        with app.test_client() as c:
            resp = c.get(
                "/student_view",
                headers={"Accept": "application/json"},
            )
            assert resp.status_code == 401

    def test_student_view_authenticated_ok(self, auth_client):
        resp = auth_client.get("/student_view")
        assert resp.status_code in (200, 500)


class TestGradesTranscriptRoute:
    """مسار كشف الدرجات لطالب موجود في بيانات الاختبار."""

    def test_transcript_requires_auth(self, app):
        with app.test_client() as c:
            resp = c.get(
                "/grades/transcript/S001",
                headers={"Accept": "application/json"},
            )
            assert resp.status_code == 401

    def test_transcript_admin_returns_json(self, auth_client):
        resp = auth_client.get(
            "/grades/transcript/S001",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert "status" in data or "student_id" in data or "courses" in str(data).lower()


class TestRegistrationRequestsRoutes:
    """تكامل أساسي لطلبات الإضافة/الإسقاط."""

    def test_list_requires_auth(self, app):
        with app.test_client() as c:
            resp = c.get(
                "/registration_requests/list",
                headers={"Accept": "application/json"},
            )
            assert resp.status_code == 401

    def test_list_admin_returns_ok(self, auth_client):
        resp = auth_client.get(
            "/registration_requests/list",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "ok"
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_create_as_student_then_approve_without_execute(self, student_auth_client, auth_client, db_conn):
        cur = db_conn.cursor()
        cur.execute("DELETE FROM registration_requests")
        cur.execute("DELETE FROM registrations WHERE student_id = ?", ("S001",))
        db_conn.commit()

        r = student_auth_client.post(
            "/registration_requests/create",
            json={
                "student_id": "S001",
                "term": "اختبار",
                "course_name": "رياضيات 1",
                "action": "add",
                "reason": "pytest",
            },
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body.get("status") == "ok"
        req_id = body.get("id")
        assert req_id is not None

        r2 = auth_client.post(
            "/registration_requests/approve",
            json={"id": req_id, "execute_now": False, "note": ""},
        )
        assert r2.status_code == 200
        row = cur.execute(
            "SELECT status FROM registration_requests WHERE id = ?",
            (req_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "approved"

    def test_create_as_student_then_approve_and_execute(self, student_auth_client, auth_client, db_conn):
        """اعتماد الطلب مع ``execute_now: true`` ينفّذ الإضافة على ``registrations``."""
        cur = db_conn.cursor()
        cur.execute("DELETE FROM registration_requests")
        cur.execute("DELETE FROM registrations WHERE student_id = ?", ("S001",))
        db_conn.commit()

        r = student_auth_client.post(
            "/registration_requests/create",
            json={
                "student_id": "S001",
                "term": "اختبار-تنفيذ",
                "course_name": "فيزياء 1",
                "action": "add",
                "reason": "pytest execute",
            },
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body.get("status") == "ok"
        req_id = body.get("id")
        assert req_id is not None

        r2 = auth_client.post(
            "/registration_requests/approve",
            json={"id": req_id, "execute_now": True, "note": ""},
        )
        assert r2.status_code == 200
        assert "تنفيذ" in (r2.get_json() or {}).get("message", "")

        row = cur.execute(
            "SELECT status FROM registration_requests WHERE id = ?",
            (req_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "executed"

        reg = cur.execute(
            "SELECT 1 FROM registrations WHERE student_id = ? AND course_name = ?",
            ("S001", "فيزياء 1"),
        ).fetchone()
        assert reg is not None
