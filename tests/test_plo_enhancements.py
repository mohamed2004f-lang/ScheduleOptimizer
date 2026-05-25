"""اختبارات تحسينات كتالوج PLO."""

from backend.core.plo_benchmarks import TEMPLATES_BY_CODE, templates_for_program
from backend.core.plo_glo import next_coverage_level
from backend.core.plo_schema import ensure_plo_enhancement_schema
from backend.core import plo_benchmarks as pb_mod


def test_next_coverage_cycle():
    assert next_coverage_level("") == "I"
    assert next_coverage_level("I") == "R"
    assert next_coverage_level("R") == "M"
    assert next_coverage_level("M") == ""


def test_benchmark_templates_for_mech_department(db_conn):
    ensure_plo_enhancement_schema(db_conn)
    cur = db_conn.cursor()
    row = cur.execute(
        "SELECT id FROM departments WHERE UPPER(TRIM(code)) = 'MECH' LIMIT 1"
    ).fetchone()
    if not row:
        return
    dept_id = int(row[0] if not hasattr(row, "keys") else row["id"])
    prow = cur.execute(
        "SELECT id FROM programs WHERE department_id = ? AND COALESCE(is_active,1)=1 LIMIT 1",
        (dept_id,),
    ).fetchone()
    if not prow:
        return
    pid = int(prow[0] if not hasattr(prow, "keys") else prow["id"])
    items = templates_for_program(cur, pid)
    codes = {x["code"] for x in items}
    assert "abet_v7" in codes
    assert "mech_sos_2026" in codes
    recommended = [x["code"] for x in items if x.get("recommended")]
    if recommended:
        assert "mech_sos_2026" in recommended or "abet_v7" in recommended


def test_import_abet_template(app, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    cur = db_conn.cursor()
    prow = cur.execute(
        "SELECT p.id FROM programs p JOIN departments d ON d.id = p.department_id "
        "WHERE UPPER(TRIM(d.code)) = 'CIVIL' LIMIT 1"
    ).fetchone()
    if not prow:
        return
    pid = int(prow[0] if not hasattr(prow, "keys") else prow["id"])
    code = "__TEST_PLO_ZZ__"
    cur.execute(
        "DELETE FROM program_learning_outcomes WHERE program_id = ? AND code LIKE 'PLO%'",
        (pid,),
    )
    db_conn.commit()
    result = pb_mod.import_template(cur, pid, "civil_abet", merge=True, actor="test")
    assert result["status"] == "ok"
    assert result["inserted"] >= 8
    db_conn.commit()
    cnt = cur.execute(
        "SELECT COUNT(*) FROM program_learning_outcomes WHERE program_id = ?",
        (pid,),
    ).fetchone()[0]
    assert int(cnt) >= 8
    cur.execute(
        "DELETE FROM program_learning_outcomes WHERE program_id = ? AND code LIKE 'PLO%'",
        (pid,),
    )
    db_conn.commit()


def test_civil_track_templates_listed(db_conn):
    ensure_plo_enhancement_schema(db_conn)
    cur = db_conn.cursor()
    prow = cur.execute(
        """
        SELECT p.id FROM programs p
        JOIN departments d ON d.id = p.department_id
        WHERE UPPER(TRIM(d.code)) = 'CIVIL' AND COALESCE(p.track_group,'') = 'STR'
        LIMIT 1
        """
    ).fetchone()
    if not prow:
        from backend.core.program_tracks import ensure_department_track_programs

        ensure_department_track_programs(db_conn, "CIVIL")
        db_conn.commit()
        prow = cur.execute(
            """
            SELECT p.id FROM programs p
            JOIN departments d ON d.id = p.department_id
            WHERE UPPER(TRIM(d.code)) = 'CIVIL' AND COALESCE(p.track_group,'') = 'STR'
            LIMIT 1
            """
        ).fetchone()
    if not prow:
        return
    pid = int(prow[0] if not hasattr(prow, "keys") else prow["id"])
    codes = {t["code"] for t in templates_for_program(cur, pid)}
    assert "civil_str" in codes


def test_plo_excel_roundtrip(db_conn):
    ensure_plo_enhancement_schema(db_conn)
    from backend.core.plo_excel import export_program_outcomes_xlsx, import_outcomes_from_xlsx, template_xlsx_bytes

    assert len(template_xlsx_bytes()) > 500
    cur = db_conn.cursor()
    prow = cur.execute("SELECT id FROM programs LIMIT 1").fetchone()
    if not prow:
        return
    pid = int(prow[0] if not hasattr(prow, "keys") else prow["id"])
    code = "PLO_EXCEL_TEST"
    cur.execute(
        "DELETE FROM program_learning_outcomes WHERE program_id = ? AND code = ?",
        (pid, code),
    )
    db_conn.commit()
    rows = [
        {
            "code": code,
            "title_ar": "اختبار إكسل",
            "title_en": "Excel Test",
            "domain": "skills",
            "bloom_level": "apply",
            "performance_indicator": "≥70%",
            "accreditation_tag": "TEST",
            "parent_glo_code": "GLO1",
            "description": "وصف",
            "sort_order": 99,
            "governance_status": "draft",
            "effective_from": "",
            "is_active": 1,
        }
    ]
    xbytes = export_program_outcomes_xlsx(rows)
    result = import_outcomes_from_xlsx(cur, pid, xbytes, merge=True)
    assert result["status"] == "ok"
    assert result["inserted"] >= 1
    db_conn.commit()
    cur.execute(
        "DELETE FROM program_learning_outcomes WHERE program_id = ? AND code = ?",
        (pid, code),
    )
    db_conn.commit()


def test_plo_api_benchmarks_and_glo(app):
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        glo = c.get("/academic_quality/ilo/api/glo")
        assert glo.status_code == 200
        assert len((glo.get_json() or {}).get("items") or []) >= 8
        progs = c.get("/academic_quality/ilo/api/programs")
        items = (progs.get_json() or {}).get("items") or []
        if not items:
            return
        pid = items[0]["id"]
        tpl = c.get(f"/academic_quality/ilo/api/benchmark_templates?program_id={pid}")
        assert tpl.status_code == 200
        analytics = c.get(f"/academic_quality/ilo/api/programs/{pid}/analytics")
        assert analytics.status_code == 200
        assert "coverage_by_outcome" in (analytics.get_json() or {})
        tpl_x = c.get(f"/academic_quality/ilo/api/programs/{pid}/outcomes/template.xlsx")
        assert tpl_x.status_code == 200
        assert "spreadsheet" in (tpl_x.content_type or "")
