"""اختبارات حماية admin_main من العميد."""

from __future__ import annotations

import pytest

from backend.core.auth import hash_password


def _login(client, username: str, password: str = "TestP@ssw0rd!"):
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
        content_type="application/json",
    )


def _seed(conn):
    from backend.boot.role_profiles_seed import seed_role_profiles

    seed_role_profiles(conn)
    cur = conn.cursor()
    pw = hash_password("TestP@ssw0rd!")
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, is_system_account)
        VALUES ('sys-admin', ?, 'system_admin', 1)
        ON CONFLICT(username) DO UPDATE SET role='system_admin', is_system_account=1
        """,
        (pw,),
    )
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role)
        VALUES ('dean-user', ?, 'college_dean')
        ON CONFLICT(username) DO UPDATE SET role='college_dean', is_system_account=0
        """,
        (pw,),
    )
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role)
        VALUES ('main-admin', ?, 'admin_main')
        ON CONFLICT(username) DO UPDATE SET role='admin_main'
        """,
        (pw,),
    )
    cur.execute(
        """
        INSERT INTO students (student_id, student_name, enrollment_status)
        VALUES ('ST-DEAN-1', 'طالب اختبار العميد', 'active')
        ON CONFLICT(student_id) DO UPDATE SET student_name='طالب اختبار العميد'
        """
    )
    conn.commit()


@pytest.fixture
def dean_admin_db(app):
    from backend.services.utilities import get_connection

    with get_connection() as conn:
        _seed(conn)
    yield app


def test_dean_cannot_delete_admin_main(dean_admin_db, client):
    assert _login(client, "dean-user").status_code == 200
    res = client.post(
        "/users/delete",
        json={"username": "main-admin"},
        content_type="application/json",
    )
    assert res.status_code == 403


def test_dean_cannot_assign_admin_main(dean_admin_db, client):
    assert _login(client, "dean-user").status_code == 200
    res = client.post(
        "/users/add",
        json={
            "username": "new-admin-try",
            "password": "TryP@ss1!",
            "role": "admin_main",
            "is_active": True,
        },
        content_type="application/json",
    )
    assert res.status_code == 403


def test_system_admin_can_delete_admin_main(dean_admin_db, client):
    assert _login(client, "sys-admin").status_code == 200
    res = client.post(
        "/users/delete",
        json={"username": "main-admin"},
        content_type="application/json",
    )
    assert res.status_code == 200


def test_dean_can_list_students_read_only(dean_admin_db, client):
    assert _login(client, "dean-user").status_code == 200
    res = client.get("/students/list")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)
    assert any(str(s.get("student_id")) == "ST-DEAN-1" for s in data)
    blocked = client.post(
        "/students/add",
        json={"student_id": "ST-NEW", "student_name": "x"},
        content_type="application/json",
    )
    assert blocked.status_code == 403
