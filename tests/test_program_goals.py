"""اختبارات أهداف البرنامج ومخرجات ميكانيك."""

from backend.core.plo_schema import ensure_plo_enhancement_schema
from backend.core.program_goals import import_mech_program_profile


def _mech_program_id(db_conn):
    cur = db_conn.cursor()
    row = cur.execute(
        """
        SELECT p.id FROM programs p
        JOIN departments d ON d.id = p.department_id
        WHERE UPPER(TRIM(d.code)) = 'MECH'
          AND COALESCE(p.track_group, '') = ''
        ORDER BY p.id LIMIT 1
        """
    ).fetchone()
    if not row:
        row = cur.execute(
            """
            SELECT p.id FROM programs p
            JOIN departments d ON d.id = p.department_id
            WHERE UPPER(TRIM(d.code)) = 'MECH'
            ORDER BY p.id LIMIT 1
            """
        ).fetchone()
    if not row:
        cur.execute(
            "INSERT OR IGNORE INTO departments (code, name_ar, name_en) VALUES ('MECH', 'ميكانيك', 'Mech')"
        )
        db_conn.commit()
        did = cur.execute("SELECT id FROM departments WHERE code = 'MECH'").fetchone()[0]
        cur.execute(
            """
            INSERT INTO programs (department_id, code, name_ar, min_total_units, is_active)
            VALUES (?, 'MECH_TST', 'اختبار ميكانيك', 155, 1)
            """,
            (did,),
        )
        db_conn.commit()
        return int(cur.lastrowid)
    return int(row[0] if not hasattr(row, "keys") else row["id"])


def test_import_mech_profile(db_conn):
    ensure_plo_enhancement_schema(db_conn)
    pid = _mech_program_id(db_conn)
    cur = db_conn.cursor()
    cur.execute("DELETE FROM program_goal_outcome_links")
    cur.execute("DELETE FROM program_goals WHERE program_id = ?", (pid,))
    cur.execute(
        "DELETE FROM program_learning_outcomes WHERE program_id = ? AND code LIKE 'SO%'",
        (pid,),
    )
    db_conn.commit()

    result = import_mech_program_profile(cur, pid, merge=True, sync_links=True, actor="test")
    assert result["status"] == "ok"
    db_conn.commit()

    gcnt = cur.execute(
        "SELECT COUNT(*) FROM program_goals WHERE program_id = ? AND code LIKE 'PG%'",
        (pid,),
    ).fetchone()[0]
    ocnt = cur.execute(
        "SELECT COUNT(*) FROM program_learning_outcomes WHERE program_id = ? AND code LIKE 'SO%'",
        (pid,),
    ).fetchone()[0]
    lcnt = cur.execute(
        """
        SELECT COUNT(*) FROM program_goal_outcome_links l
        INNER JOIN program_goals g ON g.id = l.goal_id
        WHERE g.program_id = ?
        """,
        (pid,),
    ).fetchone()[0]
    assert int(gcnt) == 4
    assert int(ocnt) == 6
    assert int(lcnt) >= 8


def test_program_goals_api(auth_client, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    pid = _mech_program_id(db_conn)

    r = auth_client.post(
        f"/academic_quality/ilo/api/programs/{pid}/goals",
        json={
            "code": "PG_TEST",
            "title_ar": "هدف اختبار",
            "description": "وصف",
            "sort_order": 99,
        },
    )
    assert r.status_code == 200
    gid = (r.get_json() or {}).get("id")
    assert gid

    r2 = auth_client.get(f"/academic_quality/ilo/api/programs/{pid}/goals")
    items = (r2.get_json() or {}).get("items") or []
    assert any(x.get("code") == "PG_TEST" for x in items)

    r3 = auth_client.get(f"/academic_quality/ilo/api/programs/{pid}/goal_outcome_matrix")
    assert r3.status_code == 200
    body = r3.get_json() or {}
    assert "goals" in body and "outcomes" in body

    auth_client.delete(f"/academic_quality/ilo/api/goals/{gid}")


def test_mech_profile_import_api(auth_client, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    pid = _mech_program_id(db_conn)
    r = auth_client.post(
        f"/academic_quality/ilo/api/programs/{pid}/import_mech_profile",
        json={"merge": True, "propagate_tracks": False},
    )
    assert r.status_code == 200
    body = r.get_json() or {}
    assert body.get("status") == "ok"
    assert body.get("goals", {}).get("inserted", 0) + body.get("goals", {}).get("updated", 0) >= 4


def test_mech_sos_template_listed(db_conn):
    ensure_plo_enhancement_schema(db_conn)
    from backend.core.plo_benchmarks import templates_for_program

    cur = db_conn.cursor()
    pid = _mech_program_id(db_conn)
    items = templates_for_program(cur, pid)
    codes = {x["code"] for x in items}
    assert "mech_sos_2026" in codes
