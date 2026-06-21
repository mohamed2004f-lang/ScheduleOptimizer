"""اختبارات حماية مسؤول النظام المخفي."""

from __future__ import annotations

import pytest

from backend.core.auth import hash_password


def _login(client, username: str, password: str = "TestP@ssw0rd!"):
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
        content_type="application/json",
    )


def _seed_users(conn):
    from backend.boot.role_profiles_seed import seed_role_profiles

    seed_role_profiles(conn)
    cur = conn.cursor()
    pw = hash_password("TestP@ssw0rd!")
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, is_system_account)
        VALUES ('sys-hidden', ?, 'system_admin', 1)
        ON CONFLICT(username) DO UPDATE SET role='system_admin', is_system_account=1
        """,
        (pw,),
    )
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, is_system_account)
        VALUES ('dean-user', ?, 'college_dean', 0)
        ON CONFLICT(username) DO UPDATE SET role='college_dean', is_system_account=0
        """,
        (pw,),
    )
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role)
        VALUES ('staff-a', ?, 'staff')
        ON CONFLICT(username) DO UPDATE SET role='staff'
        """,
        (pw,),
    )
    conn.commit()


@pytest.fixture
def rbac_db(app):
    from backend.services.utilities import get_connection

    with get_connection() as conn:
        _seed_users(conn)
    yield app


def test_system_admin_hidden_from_dean_list(rbac_db, client):
    assert _login(client, "dean-user").status_code == 200
    res = client.get("/users/list")
    assert res.status_code == 200
    names = {u["username"] for u in res.get_json().get("users", [])}
    assert "sys-hidden" not in names
    assert "staff-a" in names


def test_dean_cannot_delete_system_admin(rbac_db, client):
    assert _login(client, "dean-user").status_code == 200
    res = client.post(
        "/users/delete",
        json={"username": "sys-hidden"},
        content_type="application/json",
    )
    assert res.status_code in (403, 404)


def test_dean_can_add_staff(rbac_db, client):
    assert _login(client, "dean-user").status_code == 200
    res = client.post(
        "/users/add",
        json={
            "username": "new-staff-dean",
            "password": "StaffP@ss1",
            "role": "staff",
            "is_active": True,
        },
        content_type="application/json",
    )
    assert res.status_code == 200
    assert res.get_json().get("status") == "ok"


def test_dean_cannot_assign_system_admin(rbac_db, client):
    assert _login(client, "dean-user").status_code == 200
    res = client.post(
        "/users/add",
        json={
            "username": "evil-admin",
            "password": "EvilP@ss1",
            "role": "system_admin",
            "is_active": True,
        },
        content_type="application/json",
    )
    assert res.status_code == 403


def test_system_admin_sees_all_users(rbac_db, client):
    assert _login(client, "admin-test").status_code == 200
    res = client.get("/users/list")
    assert res.status_code == 200
    names = {u["username"] for u in res.get_json().get("users", [])}
    assert "sys-hidden" in names
