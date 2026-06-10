"""اختبارات كتالوج معايير المركز (المرحلة 1)."""

from backend.core.accreditation_catalog import (
    DOMAIN_LABELS,
    ensure_accreditation_catalog,
    list_active_catalog_versions,
)
from backend.core.accreditation_evidence_catalog import INSTITUTIONAL_EVIDENCE_CHECKLIST
from backend.core.qaa_catalog_seed import ensure_qaa_catalog, seed_qaa_catalog_version
from backend.services.accreditation_evidence import _migrate_standards_pdf_checklist_keys
from backend.services.institutional_accreditation import build_compliance_map


def test_qaa_domains_defined():
    assert "qaa_mq" in DOMAIN_LABELS
    assert "qaa_inst" in DOMAIN_LABELS
    assert "qaa_prog_ug" in DOMAIN_LABELS


def test_checklist_split_standards_pdfs():
    keys = [k for k, *_ in INSTITUTIONAL_EVIDENCE_CHECKLIST]
    assert "institutional_standards_pdf" in keys
    assert "program_standards_pdf" in keys
    assert "standards_pdf" not in keys


def test_seed_qaa_catalog_versions(db_conn):
    from backend.services.institutional_accreditation import _ensure_accreditation_tables

    _ensure_accreditation_tables(db_conn)
    cur = db_conn.cursor()
    cur.execute("DELETE FROM accreditation_indicators")
    cur.execute("DELETE FROM accreditation_standards")
    db_conn.commit()
    stats = ensure_qaa_catalog(db_conn)
    inst = stats["versions"]["QAA-2023.4-INST"]
    prog = stats["versions"]["QAA-2023.4-PROG-UG"]
    assert inst["status"] == "ok"
    assert prog["status"] == "ok"
    assert inst["indicators_upserted"] >= 200
    assert prog["indicators_upserted"] >= 130

    versions = list_active_catalog_versions(db_conn)
    assert "QAA-2023.4-INST" in versions
    assert "QAA-2023.4-PROG-UG" in versions

    inst_map = build_compliance_map(
        db_conn, semester="qaa-sem", department_id=None, catalog_version="QAA-2023.4-INST", ensure_seed=False
    )
    assert inst_map["summary"]["indicators_total"] >= 200
    assert any(d["code"] == "qaa_mq" for d in inst_map["domains"])
    sample = inst_map["domains"][0]["standards"][0]["indicators"][0]
    assert not sample["title_ar"].startswith("مؤشر ")
    assert sample.get("source_type_label") == "مركز ضمان الجودة الليبي"

    prog_map = build_compliance_map(
        db_conn,
        semester="qaa-sem",
        department_id=None,
        catalog_version="QAA-2023.4-PROG-UG",
        ensure_seed=False,
    )
    assert prog_map["summary"]["indicators_total"] >= 130
    assert any(d["code"] == "qaa_prog_ug" for d in prog_map["domains"])


def test_seed_qaa_idempotent(db_conn):
    ensure_accreditation_catalog(db_conn)
    first = seed_qaa_catalog_version(db_conn, "QAA-2023.4-INST")
    second = seed_qaa_catalog_version(db_conn, "QAA-2023.4-INST")
    if first["status"] == "ok":
        assert second["status"] == "skipped"
        assert second["reason"] == "already_seeded"


def test_migrate_standards_pdf_keys(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT INTO accreditation_evidence (
            semester, department_id, checklist_key, title_ar, evidence_type,
            original_name, stored_path, uploaded_by, uploaded_at, is_active
        ) VALUES (?, NULL, 'standards_pdf', 'برامج', 'file', 'prog.pdf',
                  'college__sem__d198421abc.pdf', 't', '2020-01-01', 1)
        """,
        ("mig-sem",),
    )
    cur.execute(
        """
        INSERT INTO accreditation_evidence (
            semester, department_id, checklist_key, title_ar, evidence_type,
            original_name, stored_path, uploaded_by, uploaded_at, is_active
        ) VALUES (?, NULL, 'standards_pdf', 'مؤسسي', 'file', 'inst.pdf',
                  'college__sem__592730abc.pdf', 't', '2020-01-01', 1)
        """,
        ("mig-sem",),
    )
    db_conn.commit()
    _migrate_standards_pdf_checklist_keys(db_conn)
    rows = cur.execute(
        "SELECT checklist_key FROM accreditation_evidence WHERE semester = ? ORDER BY id",
        ("mig-sem",),
    ).fetchall()
    keys = [r[0] for r in rows]
    assert "program_standards_pdf" in keys
    assert "institutional_standards_pdf" in keys
    assert "standards_pdf" not in keys
