"""قوالب الجودة فوق دور عضو هيئة التدريس."""

from __future__ import annotations

import uuid

from backend.boot.role_profiles_seed import seed_role_profiles
from backend.core.auth import hash_password
from backend.core.permissions import get_profile_by_code


def _login(client, username: str, password: str = "TestP@ssw0rd!"):
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
        content_type="application/json",
    )


def test_quality_profiles_base_role_instructor(db_conn):
    seed_role_profiles(db_conn)
    for code in ("college_quality_head", "dept_quality_coordinator"):
        prof = get_profile_by_code(code, conn=db_conn)
        assert prof is not None
        assert prof.get("base_role") == "instructor"


def test_assign_college_quality_requires_instructor(db_conn, client):
    seed_role_profiles(db_conn)
    pw = hash_password("TestP@ssw0rd!")
    cur = db_conn.cursor()
    main = f"main_q_{uuid.uuid4().hex[:6]}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin_main')",
        (main, pw),
    )
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"Q{uuid.uuid4().hex[:4]}", "قسم جودة", "Q"),
    )
    dep_id = cur.execute("SELECT id FROM departments ORDER BY id DESC LIMIT 1").fetchone()[0]
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"جودة {uuid.uuid4().hex[:4]}", dep_id),
    )
    iid = cur.lastrowid
    staff_u = f"staff_q_{uuid.uuid4().hex[:6]}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'staff')",
        (staff_u, pw),
    )
    inst_u = f"inst_q_{uuid.uuid4().hex[:6]}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, instructor_id) VALUES (?, ?, 'instructor', ?)",
        (inst_u, pw, iid),
    )
    db_conn.commit()

    _login(client, main)
    bad = client.post(
        "/users/add",
        json={
            "username": staff_u,
            "role": "staff",
            "is_active": True,
            "role_profile_code": "college_quality_head",
        },
        content_type="application/json",
    )
    assert bad.status_code == 400

    ok = client.post(
        "/users/add",
        json={
            "username": inst_u,
            "role": "instructor",
            "instructor_id": iid,
            "is_active": True,
            "role_profile_code": "college_quality_head",
        },
        content_type="application/json",
    )
    assert ok.status_code == 200, ok.get_json()
    row = cur.execute(
        "SELECT COALESCE(is_college_quality_lead,0), role_profile_id FROM users WHERE username = ?",
        (inst_u,),
    ).fetchone()
    assert int(row[0]) == 1
    assert row[1] is not None
