"""صلاحيات لائحة الإنذارات وقرارات الفصل."""

from __future__ import annotations

import uuid

from backend.core.auth import hash_password


def _ensure_rules_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS academic_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT,
            value_number REAL,
            value_text TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.commit()


def _insert_user(conn, *, username: str, role: str, is_supervisor: int = 0) -> None:
    pw = hash_password("TestP@ssw0rd!")
    conn.execute(
        """
        INSERT INTO users (username, password_hash, role, is_supervisor)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            password_hash = excluded.password_hash,
            role = excluded.role,
            is_supervisor = excluded.is_supervisor
        """,
        (username, pw, role, int(is_supervisor)),
    )
    conn.commit()


def _login(client, username: str):
    return client.post(
        "/auth/login",
        json={"username": username, "password": "TestP@ssw0rd!"},
        content_type="application/json",
    )


def test_admin_can_list_academic_rules(auth_client, db_conn):
    _ensure_rules_table(db_conn)
    res = auth_client.get("/academic_rules/list")
    assert res.status_code == 200
    rules = (res.get_json() or {}).get("rules") or []
    assert len(rules) >= 1
    keys = {r.get("rule_key") for r in rules}
    assert "dismissal_cgpa_threshold" in keys


def test_dean_can_list_and_save_academic_rules(app, db_conn):
    _ensure_rules_table(db_conn)
    uid = uuid.uuid4().hex[:8]
    dean_user = f"dean_rules_{uid}"
    _insert_user(db_conn, username=dean_user, role="college_dean")

    with app.test_client() as client:
        assert _login(client, dean_user).status_code == 200
        page = client.get("/academic_rules_page")
        assert page.status_code == 200

        listed = client.get("/academic_rules/list")
        assert listed.status_code == 200
        rules = (listed.get_json() or {}).get("rules") or []
        assert len(rules) >= 1
        target = next(r for r in rules if r.get("rule_key") == "dismissal_cgpa_threshold")

        saved = client.post(
            "/academic_rules/save",
            json={
                "id": target["id"],
                "rule_key": target["rule_key"],
                "title": target["title"],
                "description": target["description"],
                "category": target["category"],
                "value_number": 36,
                "value_text": "dean-note",
                "is_active": True,
            },
            content_type="application/json",
        )
        assert saved.status_code == 200
        assert (saved.get_json() or {}).get("status") == "ok"

        again = client.get("/academic_rules/list")
        updated = next(
            r
            for r in ((again.get_json() or {}).get("rules") or [])
            if r.get("rule_key") == "dismissal_cgpa_threshold"
        )
        assert float(updated.get("value_number")) == 36.0
        assert updated.get("value_text") == "dean-note"


def test_dean_instructor_mode_cannot_access_academic_rules(app, db_conn):
    _ensure_rules_table(db_conn)
    uid = uuid.uuid4().hex[:8]
    dean_user = f"dean_rules_inst_{uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO instructors (name, type, is_active) VALUES (?, 'internal', 1)",
        (f"عميد اختبار {uid}",),
    )
    instructor_id = cur.lastrowid
    pw = hash_password("TestP@ssw0rd!")
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, is_supervisor, instructor_id)
        VALUES (?, ?, 'college_dean', 1, ?)
        """,
        (dean_user, pw, instructor_id),
    )
    db_conn.commit()

    with app.test_client() as client:
        assert _login(client, dean_user).status_code == 200
        switched = client.post(
            "/auth/active_mode",
            json={"mode": "instructor"},
            content_type="application/json",
        )
        assert switched.status_code == 200
        listed = client.get("/academic_rules/list")
        assert listed.status_code == 403


def test_student_cannot_list_academic_rules(student_auth_client, db_conn):
    _ensure_rules_table(db_conn)
    res = student_auth_client.get(
        "/academic_rules/list",
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    assert res.status_code == 403
