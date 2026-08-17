"""قائمة المتطلبات المسبقة يجب أن تطابق خريطة المتطلبات ضمن نطاق رئيس القسم."""

from tests.test_users_routes import head_auth_client  # noqa: F401


def _seed_mech_prereqs(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) "
        "VALUES ('MECH', 'الميكانيكا', 'Mechanical', 1)"
    )
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) "
        "VALUES ('ELEC', 'الكهرباء', 'Electrical', 1)"
    )
    mech_id = int(cur.execute("SELECT id FROM departments WHERE code='MECH'").fetchone()[0])
    elec_id = int(cur.execute("SELECT id FROM departments WHERE code='ELEC'").fetchone()[0])
    cur.execute(
        "INSERT OR IGNORE INTO instructors (id, name, department_id) VALUES (7, 'رئيس ميكانيكا', ?)",
        (mech_id,),
    )
    cur.execute("UPDATE instructors SET department_id = ? WHERE id = 7", (mech_id,))
    cur.execute("UPDATE users SET department_id = ? WHERE username = 'head-test'", (mech_id,))
    cur.execute(
        """
        INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id)
        VALUES ('آلات دوارة', 'ME 409', 3, ?)
        """,
        (mech_id,),
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id)
        VALUES ('الرسم الهندسي', 'GE 102', 3, ?)
        """,
        (mech_id,),
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id)
        VALUES ('دوائر كهربائية', 'EE 201', 3, ?)
        """,
        (elec_id,),
    )
    cur.execute(
        "INSERT OR IGNORE INTO prereqs (course_name, required_course_name) VALUES ('آلات دوارة', 'الرسم الهندسي')"
    )
    cur.execute(
        "INSERT OR IGNORE INTO prereqs (course_name, required_course_name) VALUES ('دوائر كهربائية', 'الرسم الهندسي')"
    )
    db_conn.commit()
    return mech_id


def test_hod_prereqs_list_matches_flowchart_source(head_auth_client, db_conn):
    _seed_mech_prereqs(db_conn)
    resp = head_auth_client.get("/courses/prereqs/list")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    rows = resp.get_json()
    assert isinstance(rows, list)
    pairs = {(r["course_name"], r["required_course_name"]) for r in rows}
    assert ("آلات دوارة", "الرسم الهندسي") in pairs
    assert ("دوائر كهربائية", "الرسم الهندسي") not in pairs
