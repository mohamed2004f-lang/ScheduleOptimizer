"""طلبات إنشاء حساب طالب بموافقة رئيس القسم."""

from __future__ import annotations

import uuid

from backend.core.auth import hash_password
from backend.services.student_account_requests import _ensure_table


def _login(client, username: str, password: str = "TestP@ssw0rd!"):
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
        content_type="application/json",
    )


def _seed(db_conn):
    _ensure_table(db_conn)
    uid = uuid.uuid4().hex[:8]
    pw = hash_password("TestP@ssw0rd!")
    cur = db_conn.cursor()
    dep_code = f"SA{uid}"[:12]
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (dep_code, "قسم حسابات", "SA Dept"),
    )
    dep_id = cur.execute("SELECT id FROM departments WHERE code = ?", (dep_code,)).fetchone()[0]
    sid_new = f"S{uid}1"
    sid_phone = f"S{uid}2"
    sid_existing = f"S{uid}3"
    cur.execute(
        """
        INSERT INTO students (student_id, student_name, email, phone, department_id)
        VALUES (?, 'طالب بلا هاتف', NULL, NULL, ?)
        """,
        (sid_new, dep_id),
    )
    cur.execute(
        """
        INSERT INTO students (student_id, student_name, email, phone, department_id)
        VALUES (?, 'طالب بهاتف', 'a@test.com', '0911111111', ?)
        """,
        (sid_phone, dep_id),
    )
    cur.execute(
        """
        INSERT INTO students (student_id, student_name, email, phone, department_id)
        VALUES (?, 'طالب لديه حساب', NULL, '0922222222', ?)
        """,
        (sid_existing, dep_id),
    )
    cur.execute(
        """
        INSERT INTO instructors (name, type, is_active, department_id)
        VALUES (?, 'internal', 1, ?)
        """,
        (f"رئيس {uid}", dep_id),
    )
    iid = cur.lastrowid
    hod = f"hod_sa_{uid}"
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, instructor_id, department_id)
        VALUES (?, ?, 'head_of_department', ?, ?)
        """,
        (hod, pw, iid, dep_id),
    )
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, student_id, is_active, department_id)
        VALUES (?, ?, 'student', ?, 1, ?)
        """,
        (sid_existing, pw, sid_existing, dep_id),
    )
    db_conn.commit()
    return {
        "dep_id": dep_id,
        "hod": hod,
        "sid_new": sid_new,
        "sid_phone": sid_phone,
        "sid_existing": sid_existing,
    }


def test_lookup_blocks_existing_account(client, db_conn):
    names = _seed(db_conn)
    r = client.get(f"/student_account/lookup?student_id={names['sid_existing']}")
    assert r.status_code == 409
    assert (r.get_json() or {}).get("code") == "HAS_ACCOUNT"


def test_lookup_requires_whatsapp_when_missing(client, db_conn):
    names = _seed(db_conn)
    r = client.get(f"/student_account/lookup?student_id={names['sid_new']}")
    assert r.status_code == 200
    body = r.get_json() or {}
    assert body.get("whatsapp_required") is True
    assert body.get("student_name")


def test_submit_and_hod_approve(client, db_conn):
    names = _seed(db_conn)
    # رقم مخزّن — بدون تصحيح
    bad = client.post(
        "/student_account/request",
        json={
            "student_id": names["sid_new"],
            "password": "short",
            "password_confirm": "short",
            "whatsapp_phone": "0912345678",
        },
        content_type="application/json",
    )
    assert bad.status_code == 400

    ok = client.post(
        "/student_account/request",
        json={
            "student_id": names["sid_new"],
            "password": "StudentP@ss1",
            "password_confirm": "StudentP@ss1",
            "whatsapp_phone": "0912345678",
            "email": "newstu@test.com",
        },
        content_type="application/json",
    )
    assert ok.status_code == 200, ok.get_json()
    req_id = (ok.get_json() or {}).get("id")
    assert req_id

    pending = client.get(f"/student_account/lookup?student_id={names['sid_new']}")
    assert pending.status_code == 409
    assert (pending.get_json() or {}).get("code") == "PENDING"

    assert _login(client, names["hod"]).status_code == 200
    listed = client.get("/student_account/requests?status=pending")
    assert listed.status_code == 200
    items = (listed.get_json() or {}).get("items") or []
    assert any(int(it.get("id")) == int(req_id) for it in items)

    decide = client.post(
        f"/student_account/requests/{req_id}/decide",
        json={"decision": "approve"},
        content_type="application/json",
    )
    assert decide.status_code == 200, decide.get_json()
    username = (decide.get_json() or {}).get("username")
    assert username

    row = db_conn.cursor().execute(
        "SELECT role, student_id, COALESCE(is_active,1) FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    assert row is not None
    assert row[0] == "student"
    assert str(row[1]) == names["sid_new"]
    assert int(row[2]) == 1

    phone = db_conn.cursor().execute(
        "SELECT phone FROM students WHERE student_id = ?",
        (names["sid_new"],),
    ).fetchone()[0]
    assert phone and "912345678" in str(phone).replace(" ", "")


def test_whatsapp_correction_requires_note(client, db_conn):
    names = _seed(db_conn)
    r = client.post(
        "/student_account/request",
        json={
            "student_id": names["sid_phone"],
            "password": "StudentP@ss1",
            "password_confirm": "StudentP@ss1",
            "whatsapp_correction": True,
            "alternate_whatsapp": "0933333333",
        },
        content_type="application/json",
    )
    assert r.status_code == 400

    r2 = client.post(
        "/student_account/request",
        json={
            "student_id": names["sid_phone"],
            "password": "StudentP@ss1",
            "password_confirm": "StudentP@ss1",
            "whatsapp_correction": True,
            "alternate_whatsapp": "0933333333",
            "note": "الرقم القديم لوالدي",
        },
        content_type="application/json",
    )
    assert r2.status_code == 200, r2.get_json()
