"""اختبارات مرحلة 0 (كتالوج + تعبئة طلاب بدون تعيين)."""


def test_phase0_a_catalog_inserts_programs(db_conn):
    import backend.boot.phase0 as phase0mod

    out = phase0mod.ensure_phase0_catalog(db_conn)
    db_conn.commit()

    cur = db_conn.cursor()
    n_dept = cur.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
    assert n_dept >= 5
    assert "GENERAL/PROG_U1" in out["program_ids"]
    assert "MECH/PROG_MAJOR" in out["program_ids"]


def test_phase0_b_backfill_sets_mech_major_for_seed_students(db_conn):
    import backend.boot.phase0 as phase0mod

    phase0mod.ensure_phase0_catalog(db_conn)
    res = phase0mod.backfill_legacy_students(db_conn, legacy_dept_code="MECH", dry_run=False)
    db_conn.commit()

    cur = db_conn.cursor()
    for sid in ("S001", "S002"):
        row = cur.execute(
            """
            SELECT s.student_id, d.code AS dept, p.code AS prog
            FROM students s
            LEFT JOIN departments d ON d.id = s.department_id
            LEFT JOIN programs p ON p.id = s.current_program_id
            WHERE s.student_id = ?
            """,
            (sid,),
        ).fetchone()
        assert row is not None
        dept = row[1] if not isinstance(row, dict) else row["dept"]
        prog = row[2] if not isinstance(row, dict) else row["prog"]
        assert dept == "MECH"
        assert prog == "PROG_MAJOR"
    assert int(res.get("remaining_unassigned", -1)) == 0


def test_phase0_c_backfill_dry_run_does_not_update(db_conn):
    import backend.boot.phase0 as phase0mod

    phase0mod.ensure_phase0_catalog(db_conn)
    # إعادة إخفاء التعيين لطالب واحد
    db_conn.execute(
        """
        UPDATE students SET department_id = NULL, current_program_id = NULL
        WHERE student_id = 'S001'
        """
    )
    db_conn.commit()
    before_pending = phase0mod.count_legacy_students(db_conn)
    assert before_pending >= 1
    phase0mod.backfill_legacy_students(db_conn, legacy_dept_code="MECH", dry_run=True)
    db_conn.commit()
    mid_pending = phase0mod.count_legacy_students(db_conn)
    assert mid_pending >= 1
    phase0mod.backfill_legacy_students(db_conn, legacy_dept_code="MECH", dry_run=False)
    db_conn.commit()
    after_pending = phase0mod.count_legacy_students(db_conn)
    assert after_pending == before_pending - 1


def test_phase0_d_backfill_operational_links_courses_to_mech(db_conn):
    import backend.boot.phase0 as phase0mod

    phase0mod.ensure_phase0_catalog(db_conn)
    db_conn.execute(
        "INSERT OR REPLACE INTO courses (course_name, course_code, units, owning_department_id) "
        "VALUES ('PH0_OP', 'PH0', 3, NULL)"
    )
    db_conn.commit()

    op = phase0mod.backfill_legacy_operational_data(
        db_conn,
        legacy_dept_code="MECH",
        dry_run=False,
        include_students=False,
        include_courses=True,
        include_instructors=False,
        include_staff_users=False,
    )
    db_conn.commit()

    me_id = db_conn.execute("SELECT id FROM departments WHERE code = 'MECH'").fetchone()[0]
    oid = db_conn.execute(
        "SELECT owning_department_id FROM courses WHERE course_name = 'PH0_OP'"
    ).fetchone()[0]
    assert oid == me_id
    assert int(op.get("courses_updated", 0)) >= 1


def test_phase0_e_me_monolith_courses_and_schedule(db_conn):
    import backend.boot.phase0 as phase0mod

    phase0mod.ensure_phase0_catalog(db_conn)
    me_id = db_conn.execute("SELECT id FROM departments WHERE code = 'MECH'").fetchone()[0]
    db_conn.execute(
        "INSERT OR REPLACE INTO courses (course_name, course_code, units, owning_department_id) "
        "VALUES ('MON_SC', 'MSC', 2, NULL)"
    )
    db_conn.execute(
        "INSERT INTO schedule (course_name, day, time, room, instructor, semester, department_id) "
        "VALUES ('MON_SC', 'الأحد', '08:00', 'A1', '', 'خريف 25-26', NULL)"
    )
    db_conn.commit()

    phase0mod.backfill_legacy_operational_data(
        db_conn,
        legacy_dept_code="MECH",
        dry_run=False,
        include_students=False,
        include_courses=True,
        include_instructors=False,
        include_staff_users=False,
        monolith_exclusive=True,
    )
    db_conn.commit()

    sid = db_conn.execute(
        "SELECT department_id FROM schedule WHERE course_name = 'MON_SC' LIMIT 1"
    ).fetchone()[0]
    assert sid == me_id
    oid = db_conn.execute(
        "SELECT owning_department_id FROM courses WHERE course_name = 'MON_SC'"
    ).fetchone()[0]
    assert oid == me_id
