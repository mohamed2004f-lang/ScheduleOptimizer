"""اختبارات نطاق الاعتماد المؤسسي/البرامجي وبرنامج = قسم."""

from backend.core.accreditation_catalog import (
    ACCREDITATION_MAP_SCOPES,
    INTERNAL_CATALOG_VERSION,
    QAA_INST_CATALOG_VERSION,
    QAA_PROG_UG_CATALOG_VERSION,
    ensure_accreditation_catalog,
    list_operational_catalog_versions,
    resolve_catalog_version,
    seed_internal_accreditation_catalog,
)
from backend.core.accreditation_program_scope import (
    ensure_default_program_for_department,
    resolve_accreditation_org_scope,
)
from backend.services.institutional_accreditation import build_compliance_map


def test_operational_scopes_exclude_internal():
    keys = {s["key"] for s in ACCREDITATION_MAP_SCOPES}
    assert keys == {"inst", "prog"}
    assert INTERNAL_CATALOG_VERSION not in {s["catalog_version"] for s in ACCREDITATION_MAP_SCOPES}


def test_ensure_catalog_does_not_seed_internal_by_default(db_conn):
    stats = ensure_accreditation_catalog(db_conn)
    assert stats["catalog_version"] == QAA_INST_CATALOG_VERSION
    assert stats.get("internal_seeded") is False
    cur = db_conn.cursor()
    n_internal = cur.execute(
        "SELECT COUNT(*) FROM accreditation_standards WHERE catalog_version = ?",
        (INTERNAL_CATALOG_VERSION,),
    ).fetchone()[0]
    assert int(n_internal) == 0
    assert resolve_catalog_version(db_conn) == QAA_INST_CATALOG_VERSION
    versions = list_operational_catalog_versions(db_conn)
    assert QAA_INST_CATALOG_VERSION in versions
    assert QAA_PROG_UG_CATALOG_VERSION in versions
    assert INTERNAL_CATALOG_VERSION not in versions


def test_seed_internal_still_available_for_archive(db_conn):
    seed_internal_accreditation_catalog(db_conn)
    cur = db_conn.cursor()
    n = cur.execute(
        "SELECT COUNT(*) FROM accreditation_standards WHERE catalog_version = ?",
        (INTERNAL_CATALOG_VERSION,),
    ).fetchone()[0]
    assert int(n) >= 15
    # التشغيل لا يزال يفضّل QAA
    ensure_accreditation_catalog(db_conn)
    assert resolve_catalog_version(db_conn) == QAA_INST_CATALOG_VERSION


def test_program_equals_department_today(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        ("TESTDEPT", "قسم اختبار", "Test Dept"),
    )
    db_conn.commit()
    dept_id = int(cur.execute("SELECT id FROM departments WHERE code = ?", ("TESTDEPT",)).fetchone()[0])
    ensured = ensure_default_program_for_department(db_conn, dept_id)
    assert ensured["status"] == "ok"
    assert ensured["is_base_program"] is True
    assert ensured["department_id"] == dept_id

    inst = resolve_accreditation_org_scope(db_conn, map_scope_key="inst")
    assert inst["org_level"] == "college"
    assert inst["department_id"] is None
    assert inst["program_id"] is None

    prog = resolve_accreditation_org_scope(db_conn, map_scope_key="prog", department_id=dept_id)
    assert prog["org_level"] == "program"
    assert prog["department_id"] == dept_id
    assert prog["program_id"] == ensured["program_id"]


def test_compliance_map_defaults_to_qaa_inst(db_conn):
    ensure_accreditation_catalog(db_conn)
    data = build_compliance_map(db_conn, semester="scope-sem", department_id=None, ensure_seed=False)
    assert data["catalog_version"] == QAA_INST_CATALOG_VERSION
    assert data["summary"]["indicators_total"] >= 100
