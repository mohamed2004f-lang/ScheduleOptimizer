"""اختبارات تدقيق وإصلاح رموز مخرجات البرنامج."""

from backend.core.outcome_symbol_audit import (
    audit_program_outcome_symbols,
    cleanup_mech_stray_outcomes,
)
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
        cur.execute(
            "INSERT OR IGNORE INTO departments (code, name_ar, name_en) VALUES ('MECH', 'ميكانيك', 'Mech')"
        )
        db_conn.commit()
        did = cur.execute("SELECT id FROM departments WHERE code = 'MECH'").fetchone()[0]
        cur.execute(
            """
            INSERT INTO programs (department_id, code, name_ar, min_total_units, is_active)
            VALUES (?, 'MECH_AUD', 'اختبار تدقيق', 155, 1)
            """,
            (did,),
        )
        db_conn.commit()
        return int(cur.lastrowid)
    return int(row[0] if not hasattr(row, "keys") else row["id"])


def test_audit_flags_mixed_plo_so(db_conn):
    ensure_plo_enhancement_schema(db_conn)
    pid = _mech_program_id(db_conn)
    cur = db_conn.cursor()
    import_mech_program_profile(cur, pid, merge=True, sync_links=True)
    cur.execute(
        "DELETE FROM program_learning_outcomes WHERE program_id = ? AND code = 'PLO1'",
        (pid,),
    )
    cur.execute(
        """
        INSERT INTO program_learning_outcomes (
            program_id, code, title_ar, parent_glo_code, sort_order,
            governance_status, is_active
        ) VALUES (?, 'PLO1', 'زائد', 'GLO1', 1, 'approved', 1)
        """,
        (pid,),
    )
    db_conn.commit()
    audit = audit_program_outcome_symbols(cur, pid)
    codes = {i["code"] for i in audit.get("issues") or []}
    assert "mixed_plo_so" in codes or "stray_plo_on_mech" in codes


def test_cleanup_retires_stray_plo(db_conn):
    ensure_plo_enhancement_schema(db_conn)
    pid = _mech_program_id(db_conn)
    cur = db_conn.cursor()
    import_mech_program_profile(cur, pid, merge=True, sync_links=True)
    cur.execute(
        "DELETE FROM program_learning_outcomes WHERE program_id = ? AND code = 'PLO1'",
        (pid,),
    )
    cur.execute(
        """
        INSERT INTO program_learning_outcomes (
            program_id, code, title_ar, parent_glo_code, sort_order,
            governance_status, is_active
        ) VALUES (?, 'PLO1', 'زائد', 'GLO1', 1, 'approved', 1)
        """,
        (pid,),
    )
    db_conn.commit()
    res = cleanup_mech_stray_outcomes(cur, pid)
    db_conn.commit()
    assert "PLO1" in (res.get("retired_codes") or [])
    audit = audit_program_outcome_symbols(cur, pid)
    active_codes = set(audit.get("codes") or [])
    assert "PLO1" not in active_codes
    assert "SO1" in active_codes
