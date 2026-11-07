"""اختبارات محرر قوالب الأدوار (مراحل 0–2)."""

from __future__ import annotations

import os
import uuid

from backend.core.auth import hash_password
from backend.core.permissions import (
    get_profile_by_code,
    list_role_profiles_from_db,
    load_profile_permission_keys,
)
from backend.core.role_profile_policy import LOCKED_PROFILE_CODES


def _login(client, username: str, password: str = "TestP@ssw0rd!"):
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
        content_type="application/json",
    )


def _ensure_admin_main(db_conn, username: str = "admin-main-rp"):
    from backend.boot.role_profiles_seed import seed_role_profiles

    seed_role_profiles(db_conn)
    pw = hash_password("TestP@ssw0rd!")
    cur = db_conn.cursor()
    cur.execute("DELETE FROM users WHERE username = ?", (username,))
    cur.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin_main')",
        (username, pw),
    )
    db_conn.commit()
    return username


def _ensure_dean(db_conn, username: str = "dean-rp"):
    from backend.boot.role_profiles_seed import seed_role_profiles

    seed_role_profiles(db_conn)
    pw = hash_password("TestP@ssw0rd!")
    cur = db_conn.cursor()
    cur.execute("DELETE FROM users WHERE username = ?", (username,))
    cur.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'college_dean')",
        (username, pw),
    )
    db_conn.commit()
    return username


def test_seed_does_not_wipe_custom_profile_permissions(db_conn):
    from backend.boot.role_profiles_seed import seed_role_profiles

    seed_role_profiles(db_conn)
    cur = db_conn.cursor()
    code = f"custom_clerk_{uuid.uuid4().hex[:6]}"
    cur.execute(
        """
        INSERT INTO role_profiles (code, name_ar, base_role, scope_mode, is_system, is_active)
        VALUES (?, 'كاتب مخصص', 'staff', 'college', 0, 1)
        """,
        (code,),
    )
    pid = cur.execute("SELECT id FROM role_profiles WHERE code = ?", (code,)).fetchone()[0]
    cur.execute(
        """
        INSERT INTO permission_definitions (key, group_key, group_label_ar, label_ar, sort_order)
        VALUES ('nav_performance_report', 'nav', 'قوائم', 'تقرير الأداء', 0)
        ON CONFLICT(key) DO NOTHING
        """
    )
    cur.execute(
        """
        INSERT INTO role_profile_permissions (profile_id, permission_key, granted)
        VALUES (?, 'nav_performance_report', 1)
        ON CONFLICT(profile_id, permission_key) DO UPDATE SET granted = 1
        """,
        (pid,),
    )
    db_conn.commit()

    seed_role_profiles(db_conn)
    keys = load_profile_permission_keys(db_conn, pid, code)
    assert "nav_performance_report" in keys

    # قالب seed غير مقفول: تخصيص مضاف لا يُمسح
    reg = cur.execute("SELECT id FROM role_profiles WHERE code = 'college_registrar'").fetchone()
    assert reg
    rid = int(reg[0])
    cur.execute(
        """
        INSERT INTO role_profile_permissions (profile_id, permission_key, granted)
        VALUES (?, 'nav_performance_report', 1)
        ON CONFLICT(profile_id, permission_key) DO UPDATE SET granted = 1
        """,
        (rid,),
    )
    db_conn.commit()
    seed_role_profiles(db_conn)
    reg_keys = load_profile_permission_keys(db_conn, rid, "college_registrar")
    assert "nav_performance_report" in reg_keys


def test_list_profiles_from_db_after_seed(db_conn, client):
    main = _ensure_admin_main(db_conn)
    rows = list_role_profiles_from_db(db_conn, include_system_admin=True, include_inactive=True)
    assert any(r.get("code") == "college_registrar" for r in rows)
    _login(client, main)
    res = client.get("/role_profiles/list")
    assert res.status_code == 200
    data = res.get_json() or {}
    codes = {p["code"] for p in (data.get("profiles") or [])}
    assert "college_registrar" in codes


def test_admin_main_can_update_registrar_permissions(db_conn, client):
    os.environ["ENABLE_ROLE_PROFILE_ADMIN"] = "1"
    main = _ensure_admin_main(db_conn)
    _login(client, main)
    detail = client.get("/role_profiles/detail/college_registrar")
    assert detail.status_code == 200
    before = set((detail.get_json() or {}).get("permissions") or [])
    new_keys = sorted(before | {"nav_performance_report"})
    put = client.put(
        "/role_profiles/college_registrar/permissions",
        json={"permission_keys": new_keys},
        content_type="application/json",
    )
    assert put.status_code == 200, put.get_json()
    after = set((put.get_json() or {}).get("permissions") or [])
    assert "nav_performance_report" in after
    # مفتاح خارج الكتالوج يُتجاهل
    put2 = client.put(
        "/role_profiles/college_registrar/permissions",
        json={"permission_keys": list(after) + ["not_a_real_permission_key_xyz"]},
        content_type="application/json",
    )
    assert put2.status_code == 200
    assert "not_a_real_permission_key_xyz" not in ((put2.get_json() or {}).get("permissions") or [])


def test_dean_cannot_put_permissions(db_conn, client):
    os.environ["ENABLE_ROLE_PROFILE_ADMIN"] = "1"
    dean = _ensure_dean(db_conn)
    _login(client, dean)
    res = client.put(
        "/role_profiles/college_registrar/permissions",
        json={"permission_keys": ["nav_users_admin"]},
        content_type="application/json",
    )
    assert res.status_code in (403, 302)


def test_locked_profiles_not_editable(db_conn, client):
    os.environ["ENABLE_ROLE_PROFILE_ADMIN"] = "1"
    main = _ensure_admin_main(db_conn)
    _login(client, main)
    # قوالب مقفلة موجودة في seed (admin_main قفل رمزي ولا يُزرع كقالب منفصل)
    for code in ("college_dean", "academic_vice_dean"):
        assert code in LOCKED_PROFILE_CODES
        res = client.put(
            f"/role_profiles/{code}/permissions",
            json={"permission_keys": []},
            content_type="application/json",
        )
        assert res.status_code == 403, (code, res.get_json())
    # منع إنشاء قالب برمز مقفول admin_main
    create = client.post(
        "/role_profiles",
        json={"code": "admin_main", "name_ar": "x", "base_role": "staff"},
        content_type="application/json",
    )
    assert create.status_code == 400


def test_create_archive_custom_profile(db_conn, client):
    os.environ["ENABLE_ROLE_PROFILE_ADMIN"] = "1"
    main = _ensure_admin_main(db_conn)
    _login(client, main)
    code = f"custom_fin_{uuid.uuid4().hex[:6]}"
    create = client.post(
        "/role_profiles",
        json={
            "code": code,
            "name_ar": "كاتب مالية",
            "base_role": "staff",
            "scope_mode": "college",
            "permission_keys": ["nav_performance_report"],
        },
        content_type="application/json",
    )
    assert create.status_code == 200, create.get_json()
    bad_role = client.post(
        "/role_profiles",
        json={"code": f"custom_bad_{uuid.uuid4().hex[:4]}", "name_ar": "x", "base_role": "college_dean"},
        content_type="application/json",
    )
    assert bad_role.status_code == 400
    bad_code = client.post(
        "/role_profiles",
        json={"code": "system_admin", "name_ar": "x", "base_role": "staff"},
        content_type="application/json",
    )
    assert bad_code.status_code == 400

    arch = client.post(
        f"/role_profiles/{code}/archive",
        json={},
        content_type="application/json",
    )
    assert arch.status_code == 200
    prof = get_profile_by_code(code, conn=db_conn)
    assert prof is not None
    assert int(prof.get("is_active") or 0) == 0

    # لا يُعيَّن قالب مؤرشف
    pw = hash_password("TestP@ssw0rd!")
    staff_user = f"staff_rp_{uuid.uuid4().hex[:6]}"
    db_conn.cursor().execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'staff')",
        (staff_user, pw),
    )
    db_conn.commit()
    assign = client.post(
        "/users/add",
        json={
            "username": staff_user,
            "role": "staff",
            "is_active": True,
            "role_profile_code": code,
        },
        content_type="application/json",
    )
    assert assign.status_code == 400


def test_forbidden_override_rejected(db_conn, client):
    os.environ["ENABLE_ROLE_PROFILE_ADMIN"] = "1"
    main = _ensure_admin_main(db_conn)
    _login(client, main)
    target = f"inst_ov_{uuid.uuid4().hex[:6]}"
    pw = hash_password("TestP@ssw0rd!")
    db_conn.cursor().execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'instructor')",
        (target, pw),
    )
    db_conn.commit()
    res = client.post(
        "/role_profiles/user_overrides",
        json={
            "username": target,
            "permission_key": "can_assign_system_admin",
            "granted": True,
        },
        content_type="application/json",
    )
    assert res.status_code == 400

    ok = client.post(
        "/role_profiles/user_overrides",
        json={
            "username": target,
            "permission_key": "nav_performance_report",
            "granted": True,
        },
        content_type="application/json",
    )
    assert ok.status_code == 200, ok.get_json()
