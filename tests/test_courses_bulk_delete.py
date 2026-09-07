"""حذف جماعي للمقررات ضمن نطاق القسم."""

import uuid


def test_bulk_delete_selected_and_all_in_scope(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    code = f"CIV{uid}".upper()[:12]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (code, "قسم مدني اختبار", "CivilTest"),
    )
    dep = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]
    other_code = f"OTH{uid}".upper()[:12]
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (other_code, "قسم آخر", "OtherDept"),
    )
    other_dep = cur.execute("SELECT id FROM departments WHERE code = ?", (other_code,)).fetchone()[0]
    c1 = f"Bridge Design {uid}"
    c2 = f"Airport Planning {uid}"
    c3 = f"KeepOtherDept {uid}"
    for name, owner in ((c1, dep), (c2, dep), (c3, other_dep)):
        cur.execute(
            """
            INSERT INTO courses
            (course_name, course_code, units, category, owning_department_id, is_archived)
            VALUES (?, ?, 3, 'required', ?, 0)
            """,
            (name, f"X{uid[:4]}", owner),
        )
    pw = cur.execute("SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1").fetchone()[0]
    head = f"head_civ_{uid}"
    cur.execute(
        "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
        (head, pw, dep),
    )
    db_conn.commit()

    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    with app.test_client() as c:
        assert c.post("/auth/login", json={"username": head, "password": "TestP@ssw0rd!"}).status_code == 200

        r = c.post(
            "/courses/bulk_delete",
            json={"course_names": [c1], "confirm_phrase": "تأكيد"},
            headers=headers,
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json() or {}
        assert body.get("status") == "ok"
        assert int(body.get("deleted") or 0) + int(body.get("archived") or 0) >= 1
        gone = cur.execute(
            "SELECT COUNT(*) FROM courses WHERE course_name = ? AND COALESCE(is_archived,0)=0",
            (c1,),
        ).fetchone()[0]
        assert int(gone) == 0

        r2 = c.post(
            "/courses/bulk_delete",
            json={"all_in_scope": True, "confirm_phrase": "تأكيد"},
            headers=headers,
        )
        assert r2.status_code == 200, r2.get_data(as_text=True)
        body2 = r2.get_json() or {}
        assert body2.get("status") == "ok"
        left_c2 = cur.execute(
            "SELECT COUNT(*) FROM courses WHERE course_name = ? AND COALESCE(is_archived,0)=0",
            (c2,),
        ).fetchone()[0]
        assert int(left_c2) == 0
        # مقرر بلا قسم مالك لا يدخل نطاق رئيس القسم عادة — يبقى أو يُتخطى
        still_other = cur.execute(
            "SELECT COUNT(*) FROM courses WHERE course_name = ?",
            (c3,),
        ).fetchone()[0]
        assert int(still_other) == 1
