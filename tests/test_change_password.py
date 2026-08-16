"""تغيير كلمة المرور عبر الجلسة."""
from backend.core.auth import hash_password


def test_change_password_then_login(app, db_conn):
    db_conn.execute(
        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
        ("pw-changer", hash_password("OldP@ssw0rd!"), "staff"),
    )
    db_conn.commit()
    with app.test_client() as c:
        login = c.post(
            "/auth/login",
            json={"username": "pw-changer", "password": "OldP@ssw0rd!"},
        )
        assert login.status_code == 200
        resp = c.post(
            "/auth/change_password",
            json={
                "current_password": "OldP@ssw0rd!",
                "new_password": "NewP@ssw0rd!",
                "confirm_password": "NewP@ssw0rd!",
            },
        )
        assert resp.status_code == 200
        assert (resp.get_json() or {}).get("status") == "ok"
        c.post("/auth/logout")
        assert (
            c.post(
                "/auth/login",
                json={"username": "pw-changer", "password": "OldP@ssw0rd!"},
            ).status_code
            == 401
        )
        assert (
            c.post(
                "/auth/login",
                json={"username": "pw-changer", "password": "NewP@ssw0rd!"},
            ).status_code
            == 200
        )


def test_change_password_unauthenticated(app):
    with app.test_client() as c:
        resp = c.post(
            "/auth/change_password",
            json={
                "current_password": "x",
                "new_password": "NewP@ssw0rd!",
                "confirm_password": "NewP@ssw0rd!",
            },
        )
        assert resp.status_code in (401, 302)


def test_change_password_page_requires_login(app):
    with app.test_client() as c:
        resp = c.get("/change_password", follow_redirects=False)
        assert resp.status_code in (302, 401)


def test_login_lockout_integration(app, monkeypatch):
    monkeypatch.setenv("LOGIN_LOCKOUT_ENABLED", "1")
    monkeypatch.setenv("LOGIN_LOCKOUT_MAX", "3")
    monkeypatch.setenv("LOGIN_LOCKOUT_SECONDS", "120")
    from backend.core.auth_throttle import reset_throttle_state

    reset_throttle_state()
    with app.test_client() as c:
        for _ in range(3):
            c.post(
                "/auth/login",
                json={"username": "lock-target", "password": "wrong-password"},
            )
        locked = c.post(
            "/auth/login",
            json={"username": "lock-target", "password": "wrong-password"},
        )
        assert locked.status_code == 429
        data = locked.get_json() or {}
        assert data.get("code") == "ACCOUNT_LOCKED"
        assert "لاحقاً" in (data.get("message") or "")
