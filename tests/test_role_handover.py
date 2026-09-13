"""نقل المناصب الإدارية والصلاحيات."""

from __future__ import annotations

import uuid

from backend.core.auth import hash_password
from backend.core.permissions import CAN_ADD_DEPARTMENT_USERS, load_user_overrides
from backend.repositories import users_repo


def _login(client, username: str, password: str = "TestP@ssw0rd!"):
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
        content_type="application/json",
    )


def _seed_handover_users(db_conn):
    from backend.boot.role_profiles_seed import seed_role_profiles

    seed_role_profiles(db_conn)
    uid = uuid.uuid4().hex[:8]
    pw = hash_password("TestP@ssw0rd!")
    cur = db_conn.cursor()
    dep_code = f"HO{uid}"[:12]
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (dep_code, "قسم تسليم", "Handover Dept"),
    )
    dep_id = cur.execute("SELECT id FROM departments WHERE code = ?", (dep_code,)).fetchone()[0]
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"رئيس {uid}", dep_id),
    )
    hod_iid = cur.lastrowid
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"أستاذ {uid}", dep_id),
    )
    inst_iid = cur.lastrowid
    hod_user = f"hod_ho_{uid}"
    inst_user = f"inst_ho_{uid}"
    dean_user = f"dean_ho_{uid}"
    student_user = f"st_ho_{uid}"
    main_user = f"main_ho_{uid}"
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, instructor_id, department_id, display_title_ar)
        VALUES (?, ?, 'head_of_department', ?, ?, 'رئيس قسم تسليم')
        """,
        (hod_user, pw, hod_iid, dep_id),
    )
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, instructor_id, department_id)
        VALUES (?, ?, 'instructor', ?, ?)
        """,
        (inst_user, pw, inst_iid, dep_id),
    )
    cur.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'college_dean')",
        (dean_user, pw),
    )
    cur.execute(
        "INSERT INTO users (username, password_hash, role, student_id) VALUES (?, ?, 'student', 'S001')",
        (student_user, pw),
    )
    cur.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin_main')",
        (main_user, pw),
    )
    cur.execute(
        """
        INSERT INTO user_permission_overrides (username, permission_key, granted)
        VALUES (?, ?, 1)
        """,
        (hod_user, CAN_ADD_DEPARTMENT_USERS),
    )
    db_conn.commit()
    return {
        "dep_id": dep_id,
        "hod": hod_user,
        "instructor": inst_user,
        "dean": dean_user,
        "student": student_user,
        "admin_main": main_user,
    }


def test_dean_can_handover_hod_office_to_instructor(app, db_conn):
    names = _seed_handover_users(db_conn)
    with app.test_client() as client:
        assert _login(client, names["dean"]).status_code == 200
        opts = client.get(f"/role_profiles/handover_options?from_username={names['hod']}")
        assert opts.status_code == 200
        keys = {it.get("key") for it in ((opts.get_json() or {}).get("items") or [])}
        assert "office" in keys
        assert "overrides" in keys
        assert "revert_source" in keys

        res = client.post(
            "/role_profiles/handover",
            json={
                "from_username": names["hod"],
                "to_username": names["instructor"],
                "transfer_office": True,
                "transfer_overrides": True,
                "transfer_department": True,
                "revert_source": True,
            },
        )
        assert res.status_code == 200, res.get_data(as_text=True)

    src = users_repo._user_row_to_dict(
        users_repo.fetch_user_row_by_username_ci(db_conn, names["hod"])
    )
    tgt = users_repo._user_row_to_dict(
        users_repo.fetch_user_row_by_username_ci(db_conn, names["instructor"])
    )
    assert src["role"] == "instructor"
    assert tgt["role"] == "head_of_department"
    assert int(tgt.get("department_id") or 0) == int(names["dep_id"])
    grants, _denies = load_user_overrides(db_conn, names["instructor"])
    assert CAN_ADD_DEPARTMENT_USERS in grants
    src_grants, _ = load_user_overrides(db_conn, names["hod"])
    assert CAN_ADD_DEPARTMENT_USERS not in src_grants


def test_dean_cannot_handover_college_dean_office(app, db_conn):
    names = _seed_handover_users(db_conn)
    with app.test_client() as client:
        assert _login(client, names["dean"]).status_code == 200
        res = client.post(
            "/role_profiles/handover",
            json={
                "from_username": names["dean"],
                "to_username": names["instructor"],
                "transfer_office": True,
                "transfer_overrides": False,
                "revert_source": True,
            },
        )
        assert res.status_code == 403


def test_admin_main_can_handover_college_dean_office(app, db_conn):
    names = _seed_handover_users(db_conn)
    with app.test_client() as client:
        assert _login(client, names["admin_main"]).status_code == 200
        res = client.post(
            "/role_profiles/handover",
            json={
                "from_username": names["dean"],
                "to_username": names["instructor"],
                "transfer_office": True,
                "transfer_overrides": False,
                "transfer_department": False,
                "revert_source": True,
            },
        )
        assert res.status_code == 200, res.get_data(as_text=True)

    src = users_repo._user_row_to_dict(
        users_repo.fetch_user_row_by_username_ci(db_conn, names["dean"])
    )
    tgt = users_repo._user_row_to_dict(
        users_repo.fetch_user_row_by_username_ci(db_conn, names["instructor"])
    )
    assert tgt["role"] == "college_dean"
    assert src["role"] == "staff"


def test_handover_rejects_student_accounts(app, db_conn):
    names = _seed_handover_users(db_conn)
    with app.test_client() as client:
        assert _login(client, names["admin_main"]).status_code == 200
        res = client.post(
            "/role_profiles/handover",
            json={
                "from_username": names["student"],
                "to_username": names["instructor"],
                "transfer_office": True,
            },
        )
        assert res.status_code == 400
        res2 = client.post(
            "/role_profiles/handover",
            json={
                "from_username": names["hod"],
                "to_username": names["student"],
                "transfer_office": True,
            },
        )
        assert res2.status_code == 400
