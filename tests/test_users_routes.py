"""
اختبارات تكامل لمسارات إدارة المستخدمين.
"""
import pytest


def _ensure_user(db_conn, username: str, role: str, password: str, instructor_id=None):
    try:
        from werkzeug.security import generate_password_hash
        pw_hash = generate_password_hash(password)
    except ImportError:
        from backend.core.auth import hash_password
        pw_hash = hash_password(password)
    db_conn.execute(
        """
        INSERT OR REPLACE INTO users
        (username, password_hash, role, student_id, instructor_id, is_supervisor, is_active)
        VALUES (?, ?, ?, NULL, ?, 0, 1)
        """,
        (username, pw_hash, role, instructor_id),
    )
    db_conn.commit()


@pytest.fixture
def head_auth_client(app, db_conn):
    _ensure_user(
        db_conn=db_conn,
        username="head-test",
        role="head_of_department",
        password="HeadP@ss123",
        instructor_id=7,
    )
    with app.test_client() as c:
        resp = c.post("/auth/login", json={"username": "head-test", "password": "HeadP@ss123"})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        yield c


class TestUsersAddValidation:
    def test_admin_create_student_requires_student_id(self, auth_client):
        resp = auth_client.post(
            "/users/add",
            json={"username": "student-no-id", "password": "XyZ!12345", "role": "student"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "student_id" in (data.get("message") or "")

    def test_admin_create_instructor_requires_instructor_id(self, auth_client):
        resp = auth_client.post(
            "/users/add",
            json={"username": "inst-no-id", "password": "XyZ!12345", "role": "instructor"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "instructor_id" in (data.get("message") or "")

    def test_admin_create_student_clears_instructor_link(self, auth_client):
        resp = auth_client.post(
            "/users/add",
            json={
                "username": "student-clean-links",
                "password": "XyZ!12345",
                "role": "student",
                "student_id": "S001",
                "instructor_id": 99,
                "is_supervisor": True,
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["user"]["role"] == "student"
        assert data["user"]["student_id"] == "S001"
        assert data["user"]["instructor_id"] is None
        assert int(data["user"]["is_supervisor"]) == 0

    def test_admin_create_instructor_clears_student_link(self, auth_client):
        resp = auth_client.post(
            "/users/add",
            json={
                "username": "inst-clean-links",
                "password": "XyZ!12345",
                "role": "instructor",
                "student_id": "S001",
                "instructor_id": 7,
                "is_supervisor": True,
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["user"]["role"] == "instructor"
        assert data["user"]["student_id"] is None
        assert int(data["user"]["instructor_id"]) == 7
        assert int(data["user"]["is_supervisor"]) == 1

    def test_head_cannot_create_new_user(self, head_auth_client):
        resp = head_auth_client.post(
            "/users/add",
            json={
                "username": "new-user-by-head",
                "password": "XyZ!12345",
                "role": "instructor",
                "instructor_id": 2,
            },
        )
        assert resp.status_code == 403

    def test_admin_create_instructor_appears_in_list(self, auth_client):
        create_resp = auth_client.post(
            "/users/add",
            json={
                "username": "inst-visible-in-list",
                "password": "XyZ!12345",
                "role": "instructor",
                "instructor_id": 7,
                "is_active": True,
            },
        )
        assert create_resp.status_code == 200
        create_data = create_resp.get_json()
        assert create_data["status"] == "ok"
        assert create_data["user"]["username"] == "inst-visible-in-list"
        assert create_data["user"]["role"] == "instructor"
        assert int(create_data["user"]["instructor_id"]) == 7

        list_resp = auth_client.get("/users/list")
        assert list_resp.status_code == 200
        list_data = list_resp.get_json()
        users = list_data.get("users") or []
        saved = next((u for u in users if u.get("username") == "inst-visible-in-list"), None)
        assert saved is not None
        assert saved["role"] == "instructor"
        assert int(saved["instructor_id"]) == 7


class TestUsersAuditAndReport:
    def test_validation_report_endpoint_returns_summary(self, auth_client):
        resp = auth_client.get("/users/validation_report")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "total_users" in data
        assert "invalid_count" in data
        assert isinstance(data.get("invalid_users"), list)

    def test_audit_log_endpoint_returns_items(self, auth_client):
        resp = auth_client.get("/users/audit_log?limit=10")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "count" in data
        assert isinstance(data.get("items"), list)

    def test_audit_log_records_user_changes(self, auth_client, db_conn):
        db_conn.execute("DELETE FROM activity_log")
        db_conn.commit()

        r_add = auth_client.post(
            "/users/add",
            json={
                "username": "audit-user",
                "password": "XyZ!12345",
                "role": "instructor",
                "instructor_id": 7,
                "is_supervisor": False,
            },
        )
        assert r_add.status_code == 200

        r_toggle = auth_client.post(
            "/users/toggle_active",
            json={"username": "audit-user", "active": False},
        )
        assert r_toggle.status_code == 200

        r_delete = auth_client.post("/users/delete", json={"username": "audit-user"})
        assert r_delete.status_code == 200

        rows = db_conn.execute(
            """
            SELECT action
            FROM activity_log
            WHERE action IN ('users.created', 'users.updated', 'users.toggle_active', 'users.deleted')
            ORDER BY id
            """
        ).fetchall()
        actions = [r[0] for r in rows]
        assert "users.created" in actions or "users.updated" in actions
        assert "users.toggle_active" in actions
        assert "users.deleted" in actions
