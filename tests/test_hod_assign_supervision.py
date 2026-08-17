"""رئيس القسم يسند طلبة قسمه لمشرف دون تجاوز نطاق القسم."""

from tests.test_users_routes import head_auth_client  # noqa: F401


def _seed_scope(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES ('MECH', 'الميكانيكا', 'Mechanical', 1)"
    )
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES ('ELEC', 'الكهرباء', 'Electrical', 1)"
    )
    mech_id = int(cur.execute("SELECT id FROM departments WHERE code='MECH'").fetchone()[0])
    elec_id = int(cur.execute("SELECT id FROM departments WHERE code='ELEC'").fetchone()[0])
    cur.execute(
        """
        INSERT OR IGNORE INTO instructors (id, name, department_id, email)
        VALUES (7, 'رئيس ميكانيكا للاختبار', ?, 'hod-mech@example.com')
        """,
        (mech_id,),
    )
    cur.execute("UPDATE instructors SET department_id = ? WHERE id = 7", (mech_id,))
    cur.execute(
        """
        INSERT OR IGNORE INTO instructors (id, name, department_id, email)
        VALUES (7702, 'أستاذ ميكانيكا مشرف', ?, 'mech-sup@example.com')
        """,
        (mech_id,),
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO instructors (id, name, department_id, email)
        VALUES (7703, 'أستاذ كهرباء', ?, 'elec-sup@example.com')
        """,
        (elec_id,),
    )
    cur.execute(
        "UPDATE students SET department_id = ? WHERE student_id = 'S001'",
        (mech_id,),
    )
    cur.execute(
        "UPDATE students SET department_id = ? WHERE student_id = 'S002'",
        (elec_id,),
    )
    cur.execute("UPDATE users SET department_id = ? WHERE username = 'head-test'", (mech_id,))
    db_conn.commit()
    return mech_id, elec_id


def test_hod_lists_only_department_students(head_auth_client, db_conn):
    _seed_scope(db_conn)
    resp = head_auth_client.get("/instructors/available_students")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    ids = {s["student_id"] for s in (resp.get_json() or {}).get("students") or []}
    assert "S001" in ids
    assert "S002" not in ids


def test_hod_assigns_department_students(head_auth_client, db_conn):
    _seed_scope(db_conn)
    db_conn.execute(
        "INSERT OR IGNORE INTO student_supervisor (student_id, instructor_id) VALUES ('S002', 7702)"
    )
    db_conn.commit()
    resp = head_auth_client.post(
        "/instructors/assign_students",
        json={"instructor_id": 7702, "student_ids": ["S001"]},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["status"] == "ok"
    assert int(data["assigned_count"]) == 1
    rows = db_conn.execute(
        "SELECT student_id FROM student_supervisor WHERE instructor_id = 7702 ORDER BY student_id"
    ).fetchall()
    assigned = {r[0] for r in rows}
    assert assigned == {"S001", "S002"}


def test_hod_cannot_assign_other_department_student(head_auth_client, db_conn):
    _seed_scope(db_conn)
    resp = head_auth_client.post(
        "/instructors/assign_students",
        json={"instructor_id": 7702, "student_ids": ["S002"]},
    )
    assert resp.status_code == 400, resp.get_data(as_text=True)


def test_hod_cannot_assign_other_department_instructor(head_auth_client, db_conn):
    _seed_scope(db_conn)
    resp = head_auth_client.post(
        "/instructors/assign_students",
        json={"instructor_id": 7703, "student_ids": ["S001"]},
    )
    assert resp.status_code == 403, resp.get_data(as_text=True)
