"""تعيين رئيس قسم لقسم مختلف عن قسم الأستاذ الوظيفي (مثل الاتجاه العام)."""

from backend.core.department_scope_policy import resolve_hod_managed_department_id
from tests.test_users_routes import head_auth_client  # noqa: F401


def _seed_depts_and_instructor(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES ('GENERAL', 'الاتجاه العام', 'General', 1)"
    )
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES ('ELEC', 'الكهرباء', 'Electrical', 1)"
    )
    gen_id = int(cur.execute("SELECT id FROM departments WHERE code='GENERAL'").fetchone()[0])
    elec_id = int(cur.execute("SELECT id FROM departments WHERE code='ELEC'").fetchone()[0])
    cur.execute(
        """
        INSERT OR IGNORE INTO instructors (id, name, department_id, email)
        VALUES (7701, 'أستاذ كهرباء للاختبار', ?, 'elec-hod-test@example.com')
        """,
        (elec_id,),
    )
    db_conn.commit()
    return gen_id, elec_id


def test_resolve_hod_managed_dept_explicit_general(db_conn):
    gen_id, elec_id = _seed_depts_and_instructor(db_conn)
    dept, err = resolve_hod_managed_department_id(
        db_conn,
        role="head_of_department",
        instructor_id=7701,
        explicit_department_id=gen_id,
        actor_username="admin-test",
        actor_is_privileged=True,
    )
    assert err is None
    assert dept == gen_id
    dept2, err2 = resolve_hod_managed_department_id(
        db_conn,
        role="head_of_department",
        instructor_id=7701,
        explicit_department_id=None,
        actor_username="admin-test",
        actor_is_privileged=True,
    )
    assert err2 is None
    assert dept2 == elec_id


def test_admin_creates_hod_of_general_from_other_dept(auth_client, db_conn):
    gen_id, elec_id = _seed_depts_and_instructor(db_conn)
    resp = auth_client.post(
        "/users/add",
        json={
            "username": "hod-general-from-elec",
            "password": "XyZ!12345",
            "role": "head_of_department",
            "instructor_id": 7701,
            "department_id": gen_id,
            "is_active": True,
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["user"]["role"] == "head_of_department"
    assert int(data["user"]["instructor_id"]) == 7701
    assert int(data["user"]["department_id"]) == gen_id
    row = db_conn.execute("SELECT department_id FROM instructors WHERE id=7701").fetchone()
    assert int(row[0]) == elec_id


def test_hod_cannot_assign_outside_own_scope(head_auth_client, db_conn):
    gen_id, _elec_id = _seed_depts_and_instructor(db_conn)
    resp = head_auth_client.post(
        "/users/add",
        json={
            "username": "head-test",
            "role": "head_of_department",
            "instructor_id": 7,
            "department_id": gen_id,
            "is_active": True,
        },
    )
    assert resp.status_code in (400, 403), resp.get_data(as_text=True)
