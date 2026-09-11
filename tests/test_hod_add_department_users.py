"""منح/إلغاء صلاحية رئيس القسم بإضافة طلبة وأعضاء هيئة تدريس لقسمه فقط."""

from __future__ import annotations

import pytest

from backend.core.auth import hash_password
from backend.core.permissions import CAN_ADD_DEPARTMENT_USERS


def _ensure_tables(db_conn):
    from backend.boot.role_profiles_seed import ensure_role_profile_tables, seed_role_profiles

    ensure_role_profile_tables(db_conn)
    seed_role_profiles(db_conn)


def _seed_hod_scope(db_conn):
    _ensure_tables(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES ('MECHADD', 'ميكانيكا إضافة', 'MECHADD', 1)"
    )
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES ('ELECADD', 'كهرباء إضافة', 'ELECADD', 1)"
    )
    mech_id = int(cur.execute("SELECT id FROM departments WHERE code='MECHADD'").fetchone()[0])
    elec_id = int(cur.execute("SELECT id FROM departments WHERE code='ELECADD'").fetchone()[0])
    cur.execute(
        """
        INSERT OR IGNORE INTO instructors (id, name, type, department_id)
        VALUES (8801, 'أستاذ ميكانيكا للاختبار', 'internal', ?)
        """,
        (mech_id,),
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO instructors (id, name, type, department_id)
        VALUES (8802, 'أستاذ كهرباء للاختبار', 'internal', ?)
        """,
        (elec_id,),
    )
    cur.execute("UPDATE students SET department_id = ? WHERE student_id = 'S001'", (mech_id,))
    cur.execute("UPDATE students SET department_id = ? WHERE student_id = 'S002'", (elec_id,))
    pw = hash_password("HodAddP@ss123")
    cur.execute(
        """
        INSERT OR REPLACE INTO users
        (username, password_hash, role, student_id, instructor_id, is_supervisor, is_active, department_id)
        VALUES ('hod-add-mech', ?, 'head_of_department', NULL, 8801, 0, 1, ?)
        """,
        (pw, mech_id),
    )
    db_conn.commit()
    return mech_id, elec_id


@pytest.fixture
def hod_add_client(app, db_conn):
    _seed_hod_scope(db_conn)
    with app.test_client() as c:
        resp = c.post("/auth/login", json={"username": "hod-add-mech", "password": "HodAddP@ss123"})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        yield c


def _grant(auth_client, username: str, granted: bool):
    return auth_client.post(
        "/role_profiles/user_overrides",
        json={
            "username": username,
            "permission_key": CAN_ADD_DEPARTMENT_USERS,
            "granted": granted,
        },
    )


def test_admin_grant_and_revoke_hod_override(auth_client, db_conn):
    _seed_hod_scope(db_conn)
    r = _grant(auth_client, "hod-add-mech", True)
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    assert data["status"] == "ok"
    assert data["granted"] is True

    listed = auth_client.get("/users/list")
    assert listed.status_code == 200
    users = listed.get_json().get("users") or []
    hod = next((u for u in users if u.get("username") == "hod-add-mech"), None)
    assert hod is not None
    assert hod.get("can_add_department_users") is True

    got = auth_client.get("/role_profiles/user_overrides?username=hod-add-mech")
    assert got.status_code == 200
    assert got.get_json().get("can_add_department_users") is True

    r2 = _grant(auth_client, "hod-add-mech", False)
    assert r2.status_code == 200
    listed2 = auth_client.get("/users/list")
    hod2 = next((u for u in listed2.get_json().get("users") or [] if u.get("username") == "hod-add-mech"), None)
    assert hod2 is not None
    assert not hod2.get("can_add_department_users")


def test_cannot_grant_to_instructor(auth_client, db_conn):
    _ensure_tables(db_conn)
    r = _grant(auth_client, "inst-test", True)
    assert r.status_code == 400
    assert "رئيس القسم" in (r.get_json().get("message") or "")


def test_hod_cannot_create_without_grant(hod_add_client):
    resp = hod_add_client.post(
        "/users/add",
        json={
            "username": "new-inst-by-hod",
            "password": "XyZ!12345",
            "role": "instructor",
            "instructor_id": 8801,
        },
    )
    assert resp.status_code == 403


def test_hod_with_grant_creates_instructor_and_student(auth_client, hod_add_client, db_conn):
    assert _grant(auth_client, "hod-add-mech", True).status_code == 200

    inst = hod_add_client.post(
        "/users/add",
        json={
            "username": "mech-inst-login",
            "password": "XyZ!12345",
            "role": "instructor",
            "instructor_id": 8801,
        },
    )
    assert inst.status_code == 200, inst.get_data(as_text=True)
    inst_data = inst.get_json()
    assert inst_data["status"] == "ok"
    assert inst_data["user"]["role"] == "instructor"
    assert int(inst_data["user"]["instructor_id"]) == 8801

    stu = hod_add_client.post(
        "/users/add",
        json={
            "username": "mech-student-login",
            "password": "XyZ!12345",
            "role": "student",
            "student_id": "S001",
        },
    )
    assert stu.status_code == 200, stu.get_data(as_text=True)
    stu_data = stu.get_json()
    assert stu_data["user"]["role"] == "student"
    assert stu_data["user"]["student_id"] == "S001"


def test_hod_with_grant_cannot_create_other_dept_or_admin(auth_client, hod_add_client, db_conn):
    assert _grant(auth_client, "hod-add-mech", True).status_code == 200

    other = hod_add_client.post(
        "/users/add",
        json={
            "username": "elec-inst-by-mech-hod",
            "password": "XyZ!12345",
            "role": "instructor",
            "instructor_id": 8802,
        },
    )
    assert other.status_code == 403, other.get_data(as_text=True)

    other_stu = hod_add_client.post(
        "/users/add",
        json={
            "username": "elec-stu-by-mech-hod",
            "password": "XyZ!12345",
            "role": "student",
            "student_id": "S002",
        },
    )
    assert other_stu.status_code == 403

    admin_role = hod_add_client.post(
        "/users/add",
        json={
            "username": "admin-by-hod",
            "password": "XyZ!12345",
            "role": "admin_main",
        },
    )
    assert admin_role.status_code == 403

    hod_role = hod_add_client.post(
        "/users/add",
        json={
            "username": "hod-by-hod",
            "password": "XyZ!12345",
            "role": "head_of_department",
            "instructor_id": 8801,
        },
    )
    assert hod_role.status_code == 403


def test_hod_cannot_edit_existing_hod_account(auth_client, hod_add_client, db_conn):
    assert _grant(auth_client, "hod-add-mech", True).status_code == 200
    resp = hod_add_client.post(
        "/users/add",
        json={
            "username": "hod-add-mech",
            "role": "head_of_department",
            "instructor_id": 8801,
        },
    )
    assert resp.status_code == 403


def test_hod_cannot_read_users_audit_log(hod_add_client):
    audit = hod_add_client.get("/users/audit_log?limit=5")
    assert audit.status_code == 403
    report = hod_add_client.get("/users/validation_report")
    assert report.status_code == 403


def test_revoke_blocks_create_again(auth_client, hod_add_client, db_conn):
    assert _grant(auth_client, "hod-add-mech", True).status_code == 200
    assert _grant(auth_client, "hod-add-mech", False).status_code == 200
    resp = hod_add_client.post(
        "/users/add",
        json={
            "username": "after-revoke-inst",
            "password": "XyZ!12345",
            "role": "instructor",
            "instructor_id": 8801,
        },
    )
    assert resp.status_code == 403


def test_auth_check_nav_users_after_grant(auth_client, app, db_conn):
    _seed_hod_scope(db_conn)
    assert _grant(auth_client, "hod-add-mech", True).status_code == 200
    with app.test_client() as c:
        login = c.post("/auth/login", json={"username": "hod-add-mech", "password": "HodAddP@ss123"})
        assert login.status_code == 200
        chk = c.get("/auth/check")
        assert chk.status_code == 200
        caps = (chk.get_json() or {}).get("capabilities") or {}
        assert caps.get("can_add_department_users") is True
        assert caps.get("nav_users_admin") is True
        assert not caps.get("can_manage_users")
