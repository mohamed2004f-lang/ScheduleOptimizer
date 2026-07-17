# -*- coding: utf-8 -*-
"""صلاحيات كتابة المقررات لرئيس الاتجاه العام مقابل رئيس التخصص والمشترك للكلية."""
from __future__ import annotations

import uuid

from backend.core.auth import compute_capabilities
from backend.core.college_shared_catalog import save_catalog_entry
from backend.core.department_scope_policy import (
    actor_manages_college_general_scope,
    can_manage_college_shared_catalog,
    course_writable_by_actor,
)


def _ensure_general(cur):
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) "
        "VALUES ('GENERAL', 'الاتجاه العام', 'General', 1)"
    )
    return int(cur.execute("SELECT id FROM departments WHERE code='GENERAL'").fetchone()[0])


def test_general_hod_writes_general_not_shared_catalog(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    gen_id = _ensure_general(cur)
    ccode = f"SP{uid}"[:12].upper()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (ccode, "تخصص", "Spec"),
    )
    spec_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (ccode,)).fetchone()[0])

    gen_course = f"GenC-{uid}"
    shared_name = f"SharedC-{uid}"
    spec_course = f"SpecC-{uid}"
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (gen_course, f"G{uid[:4]}", gen_id),
    )
    cur.execute(
        "INSERT INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (spec_course, f"S{uid[:4]}", spec_id),
    )
    save_catalog_entry(
        db_conn,
        {
            "catalog_key": f"gk_{uid}",
            "share_type": "unified",
            "canonical_course_name": shared_name,
            "canonical_course_code": f"GS{uid[:3]}",
            "units": 3,
            "requirement_scope": "pre_track",
        },
    )
    pw = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
    ).fetchone()[0]
    head_gen = f"hod_gen_{uid}"
    head_spec = f"hod_sp_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head_gen, pw, gen_id),
    )
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head_spec, pw, spec_id),
    )
    db_conn.commit()

    assert actor_manages_college_general_scope(db_conn, head_gen) is True
    assert actor_manages_college_general_scope(db_conn, head_spec) is False
    # سجل المشترك: ليس لرؤساء الأقسام
    assert not can_manage_college_shared_catalog(db_conn, head_gen, user_role="head_of_department")
    assert not can_manage_college_shared_catalog(db_conn, head_spec, user_role="head_of_department")
    assert can_manage_college_shared_catalog(db_conn, "x", user_role="college_dean")
    assert can_manage_college_shared_catalog(db_conn, "x", user_role="academic_vice_dean")
    assert can_manage_college_shared_catalog(db_conn, "x", user_role="admin_main")

    assert course_writable_by_actor(db_conn, gen_course, head_gen)
    assert not course_writable_by_actor(db_conn, shared_name, head_gen)
    assert not course_writable_by_actor(db_conn, spec_course, head_gen)

    assert course_writable_by_actor(db_conn, spec_course, head_spec)
    assert not course_writable_by_actor(db_conn, gen_course, head_spec)
    assert not course_writable_by_actor(db_conn, shared_name, head_spec)

    with app.test_client() as c:
        assert c.post("/auth/login", json={"username": head_spec, "password": "TestP@ssw0rd!"}).status_code == 200
        r = c.post(
            "/courses/update",
            json={
                "old_course_name": gen_course,
                "new_course_name": gen_course,
                "units": 3,
                "course_code": f"G{uid[:4]}",
            },
        )
        assert r.status_code == 403

        assert c.post("/auth/login", json={"username": head_gen, "password": "TestP@ssw0rd!"}).status_code == 200
        r2 = c.post(
            "/courses/update",
            json={
                "old_course_name": gen_course,
                "new_course_name": gen_course,
                "units": 4,
                "course_code": f"G{uid[:4]}",
            },
        )
        assert r2.status_code == 200, r2.get_json()

        # مقرر مشترك: ممنوع على رئيس الاتجاه العام
        r_shared = c.post(
            "/courses/update",
            json={
                "old_course_name": shared_name,
                "new_course_name": shared_name,
                "units": 3,
                "course_code": f"GS{uid[:3]}",
            },
        )
        assert r_shared.status_code == 403

        r3 = c.post(
            "/college/catalog/shared_catalog/save",
            json={
                "catalog_key": f"gk2_{uid}",
                "share_type": "unified",
                "canonical_course_name": f"SharedNew-{uid}",
                "canonical_course_code": f"GN{uid[:3]}",
                "units": 2,
                "requirement_scope": "pre_track",
            },
        )
        assert r3.status_code == 403


def test_specialty_hod_cannot_save_shared_catalog(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    _ensure_general(cur)
    ccode = f"SX{uid}"[:12].upper()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (ccode, "تخصص2", "Spec2"),
    )
    spec_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (ccode,)).fetchone()[0])
    pw = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
    ).fetchone()[0]
    head = f"hod_sx_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head, pw, spec_id),
    )
    db_conn.commit()
    with app.test_client() as c:
        assert c.post("/auth/login", json={"username": head, "password": "TestP@ssw0rd!"}).status_code == 200
        r = c.post(
            "/college/catalog/shared_catalog/save",
            json={
                "catalog_key": f"deny_{uid}",
                "share_type": "unified",
                "canonical_course_name": f"Denied-{uid}",
                "canonical_course_code": f"DX{uid[:3]}",
                "units": 2,
            },
        )
        assert r.status_code == 403


def test_hod_general_no_shared_catalog_capability(db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    gen_id = _ensure_general(cur)
    pw = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
    ).fetchone()[0]
    head = f"hod_cap_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head, pw, gen_id),
    )
    db_conn.commit()
    assert actor_manages_college_general_scope(db_conn, head) is True
    assert not can_manage_college_shared_catalog(
        db_conn, head, user_role="head_of_department"
    )
    caps_admin = compute_capabilities("admin_main", 0)
    assert caps_admin.get("can_manage_college_shared_catalog") is True
    caps_vd = compute_capabilities("academic_vice_dean", 0, "vice_dean")
    assert caps_vd.get("can_manage_college_shared_catalog") is True
    caps_hod = compute_capabilities("head_of_department", 0, "head")
    assert caps_hod.get("can_manage_college_shared_catalog") is False
