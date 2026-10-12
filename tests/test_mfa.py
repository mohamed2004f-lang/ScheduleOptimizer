"""TOTP والتحقق بخطوتين للعميد ومسؤول النظام."""
import base64

from backend.core.auth import hash_password
from backend.core.mfa import mfa_enforce, role_requires_mfa
from backend.core.secret_box import decrypt_secret, encrypt_secret, is_encrypted
from backend.core.totp import generate_secret, provisioning_qr_svg, totp_at, verify_totp


def test_secret_box_roundtrip_and_legacy_plaintext():
    boxed = encrypt_secret("JBSWY3DPEHPK3PXP")
    assert is_encrypted(boxed)
    assert decrypt_secret(boxed) == "JBSWY3DPEHPK3PXP"
    assert decrypt_secret("JBSWY3DPEHPK3PXP") == "JBSWY3DPEHPK3PXP"


def test_provisioning_qr_svg_does_not_raise():
    svg = provisioning_qr_svg("JBSWY3DPEHPK3PXP", "admin-Salam")
    assert isinstance(svg, str)
    if svg:
        assert "<svg" in svg


def test_totp_rfc6238_sha1_vector():
    secret = base64.b32encode(b"12345678901234567890").decode("ascii").rstrip("=")
    assert totp_at(secret, for_time=59) == "287082"
    assert verify_totp(secret, "287082", for_time=59)
    assert verify_totp(secret, "000000", for_time=59) is False


def test_role_requires_mfa_leadership_roles():
    assert role_requires_mfa("system_admin") is True
    assert role_requires_mfa("admin_main") is True
    assert role_requires_mfa("admin") is True
    assert role_requires_mfa("college_dean") is True
    assert role_requires_mfa("academic_vice_dean") is True
    assert role_requires_mfa("head_of_department") is True
    assert role_requires_mfa("instructor") is False
    assert role_requires_mfa("student") is False
    assert role_requires_mfa("staff") is False


def test_mfa_enforce_off_in_testing(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.delenv("MFA_ENFORCE", raising=False)
    assert mfa_enforce() is False
    monkeypatch.setenv("MFA_ENFORCE", "1")
    assert mfa_enforce() is True


def test_admin_login_skips_mfa_in_tests(app):
    with app.test_client() as c:
        resp = c.post(
            "/auth/login",
            json={"username": "admin-test", "password": "TestP@ssw0rd!"},
        )
        assert resp.status_code == 200
        body = resp.get_json() or {}
        assert body.get("status") == "ok"
        assert body.get("code") not in ("MFA_REQUIRED", "MFA_SETUP_REQUIRED")


def test_dean_setup_required_when_enforced(app, db_conn, monkeypatch):
    monkeypatch.setenv("MFA_ENFORCE", "1")
    db_conn.execute(
        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
        ("dean-mfa-setup", hash_password("DeanP@ss1!"), "college_dean"),
    )
    db_conn.commit()
    with app.test_client() as c:
        resp = c.post(
            "/auth/login",
            json={"username": "dean-mfa-setup", "password": "DeanP@ss1!"},
        )
        assert resp.status_code == 200
        body = resp.get_json() or {}
        assert body.get("code") == "MFA_SETUP_REQUIRED"
        dash = c.get("/dashboard", follow_redirects=False)
        assert dash.status_code in (302, 401)
        page = c.get("/mfa/setup")
        assert page.status_code == 200
        start = c.post("/auth/mfa/setup/start", json={})
        assert start.status_code == 200, start.get_data(as_text=True)
        payload = start.get_json() or {}
        secret = payload.get("secret")
        assert secret
        assert "otpauth_uri" not in payload
        qr_svg = payload.get("qr_svg") or ""
        if qr_svg:
            assert qr_svg.startswith("<svg")
            assert "otpauth" not in page.get_data(as_text=True)
        code = totp_at(secret)
        confirm = c.post("/auth/mfa/setup/confirm", json={"code": code})
        assert confirm.status_code == 200, confirm.get_data(as_text=True)
        assert (confirm.get_json() or {}).get("status") == "ok"
        stored = db_conn.execute(
            "SELECT totp_secret FROM users WHERE username = ?",
            ("dean-mfa-setup",),
        ).fetchone()[0]
        assert stored
        assert secret not in str(stored)
        assert str(stored).startswith("enc.v1.")
        chk = c.get("/auth/check")
        assert chk.status_code == 200
        assert (chk.get_json() or {}).get("authenticated") is True or (
            chk.get_json() or {}
        ).get("user")


def test_enrolled_user_always_challenged(app, db_conn):
    secret = generate_secret()
    db_conn.execute(
        """
        INSERT INTO users (username, password_hash, role, is_active, totp_secret, totp_enabled)
        VALUES (?, ?, ?, 1, ?, 1)
        """,
        ("dean-mfa-on", hash_password("DeanP@ss1!"), "college_dean", secret),
    )
    db_conn.commit()
    with app.test_client() as c:
        first = c.post(
            "/auth/login",
            json={"username": "dean-mfa-on", "password": "DeanP@ss1!"},
        )
        assert first.status_code == 200
        assert (first.get_json() or {}).get("code") == "MFA_REQUIRED"
        page = c.get("/mfa/verify")
        assert page.status_code == 200
        bad = c.post("/auth/mfa/verify", json={"code": "000000"})
        assert bad.status_code == 401
        ok = c.post("/auth/mfa/verify", json={"code": totp_at(secret)})
        assert ok.status_code == 200, ok.get_data(as_text=True)
        assert (ok.get_json() or {}).get("status") == "ok"


def test_oneshot_totp_on_login(app, db_conn):
    secret = generate_secret()
    db_conn.execute(
        """
        INSERT INTO users (username, password_hash, role, is_active, totp_secret, totp_enabled)
        VALUES (?, ?, ?, 1, ?, 1)
        """,
        ("dean-mfa-shot", hash_password("DeanP@ss1!"), "college_dean", secret),
    )
    db_conn.commit()
    with app.test_client() as c:
        resp = c.post(
            "/auth/login",
            json={
                "username": "dean-mfa-shot",
                "password": "DeanP@ss1!",
                "totp": totp_at(secret),
            },
        )
        assert resp.status_code == 200
        assert (resp.get_json() or {}).get("status") == "ok"


def test_instructor_not_forced_when_enforce_on(app, db_conn, monkeypatch):
    monkeypatch.setenv("MFA_ENFORCE", "1")
    db_conn.execute(
        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
        ("inst-no-mfa", hash_password("InstP@ss1!"), "instructor"),
    )
    db_conn.commit()
    with app.test_client() as c:
        resp = c.post(
            "/auth/login",
            json={"username": "inst-no-mfa", "password": "InstP@ss1!"},
        )
        assert resp.status_code == 200
        assert (resp.get_json() or {}).get("status") == "ok"


def test_admin_main_can_reset_mfa_for_leadership_roles(app, db_conn, monkeypatch):
    # لا نفرض MFA على الفاعل حتى يكتمل مسار إعادة التعيين في الاختبار
    monkeypatch.delenv("MFA_ENFORCE", raising=False)
    secret = generate_secret()
    db_conn.execute(
        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
        ("admin-main-mfa", hash_password("AdminP@ss1!"), "admin_main"),
    )
    db_conn.execute(
        """
        INSERT INTO users (username, password_hash, role, is_active, totp_secret, totp_enabled)
        VALUES (?, ?, ?, 1, ?, 1)
        """,
        ("hod-lost-mfa", hash_password("HodP@ss1!"), "head_of_department", secret),
    )
    db_conn.execute(
        """
        INSERT INTO users (username, password_hash, role, is_active, totp_secret, totp_enabled)
        VALUES (?, ?, ?, 1, ?, 1)
        """,
        ("inst-has-mfa", hash_password("InstP@ss1!"), "instructor", secret),
    )
    db_conn.commit()

    with app.test_client() as c:
        login = c.post(
            "/auth/login",
            json={"username": "admin-main-mfa", "password": "AdminP@ss1!"},
        )
        assert login.status_code == 200
        assert (login.get_json() or {}).get("status") == "ok"

        ok = c.post("/users/reset_mfa", json={"username": "hod-lost-mfa"})
        assert ok.status_code == 200, ok.get_data(as_text=True)
        body = ok.get_json() or {}
        assert body.get("status") == "ok"
        assert body.get("totp_enabled") is False

        row = db_conn.execute(
            "SELECT COALESCE(totp_enabled,0), totp_secret FROM users WHERE username = ?",
            ("hod-lost-mfa",),
        ).fetchone()
        assert int(row[0] or 0) == 0
        assert row[1] in (None, "")

        denied = c.post("/users/reset_mfa", json={"username": "inst-has-mfa"})
        assert denied.status_code == 403


def test_dean_cannot_reset_mfa(app, db_conn, monkeypatch):
    monkeypatch.delenv("MFA_ENFORCE", raising=False)
    secret = generate_secret()
    db_conn.execute(
        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
        ("dean-no-reset", hash_password("DeanP@ss1!"), "college_dean"),
    )
    db_conn.execute(
        """
        INSERT INTO users (username, password_hash, role, is_active, totp_secret, totp_enabled)
        VALUES (?, ?, ?, 1, ?, 1)
        """,
        ("hod-for-dean", hash_password("HodP@ss1!"), "head_of_department", secret),
    )
    db_conn.commit()
    with app.test_client() as c:
        login = c.post(
            "/auth/login",
            json={"username": "dean-no-reset", "password": "DeanP@ss1!"},
        )
        assert login.status_code == 200
        denied = c.post("/users/reset_mfa", json={"username": "hod-for-dean"})
        assert denied.status_code in (401, 403)


def test_reset_mfa_allows_fresh_setup(app, db_conn, monkeypatch):
    secret = generate_secret()
    db_conn.execute(
        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
        ("admin-reset-flow", hash_password("AdminP@ss1!"), "admin_main"),
    )
    db_conn.execute(
        """
        INSERT INTO users (username, password_hash, role, is_active, totp_secret, totp_enabled)
        VALUES (?, ?, ?, 1, ?, 1)
        """,
        ("dean-reset-flow", hash_password("DeanP@ss1!"), "college_dean", secret),
    )
    db_conn.commit()

    with app.test_client() as admin_c:
        monkeypatch.delenv("MFA_ENFORCE", raising=False)
        assert admin_c.post(
            "/auth/login",
            json={"username": "admin-reset-flow", "password": "AdminP@ss1!"},
        ).status_code == 200
        assert admin_c.post(
            "/users/reset_mfa", json={"username": "dean-reset-flow"}
        ).status_code == 200

    monkeypatch.setenv("MFA_ENFORCE", "1")
    with app.test_client() as dean_c:
        first = dean_c.post(
            "/auth/login",
            json={"username": "dean-reset-flow", "password": "DeanP@ss1!"},
        )
        assert first.status_code == 200
        assert (first.get_json() or {}).get("code") == "MFA_SETUP_REQUIRED"


def test_admin_main_setup_required_when_enforced(app, db_conn, monkeypatch):
    monkeypatch.setenv("MFA_ENFORCE", "1")
    db_conn.execute(
        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
        ("admin-main-setup", hash_password("AdminP@ss1!"), "admin_main"),
    )
    db_conn.commit()
    with app.test_client() as c:
        resp = c.post(
            "/auth/login",
            json={"username": "admin-main-setup", "password": "AdminP@ss1!"},
        )
        assert resp.status_code == 200
        assert (resp.get_json() or {}).get("code") == "MFA_SETUP_REQUIRED"


def test_hod_setup_required_when_enforced(app, db_conn, monkeypatch):
    monkeypatch.setenv("MFA_ENFORCE", "1")
    db_conn.execute(
        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
        ("hod-mfa-setup", hash_password("HodP@ss1!"), "head_of_department"),
    )
    db_conn.commit()
    with app.test_client() as c:
        resp = c.post(
            "/auth/login",
            json={"username": "hod-mfa-setup", "password": "HodP@ss1!"},
        )
        assert resp.status_code == 200
        assert (resp.get_json() or {}).get("code") == "MFA_SETUP_REQUIRED"
