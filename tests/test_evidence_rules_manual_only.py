"""سياسة ربط الأدلة — يدوي فقط بدون بذرة آلية."""

from backend.core.accreditation_evidence_rules_seed import (
    deactivate_auto_seeded_evidence_rules,
    ensure_evidence_rules_for_catalog,
)
from backend.core.qaa_catalog_seed import ensure_qaa_catalog
from backend.core.qaa_survey_accreditation_map import QAA_INST_CATALOG
from backend.services.accreditation_evidence_bindings import build_bindable_sources, save_binding
from backend.services.accreditation_evidence_matrix import list_evidence_rules


def test_deactivate_keyword_seeded_rules(db_conn):
    from backend.core.accreditation_evidence_rules_seed import (
        _indicator_id_by_code,
        _type_id_by_code,
        _upsert_rule,
        ensure_evidence_types,
    )

    ensure_qaa_catalog(db_conn)
    ensure_evidence_types(db_conn)
    iid = _indicator_id_by_code(db_conn, QAA_INST_CATALOG, "INST-02-01")
    et_id = _type_id_by_code(db_conn, "survey_faculty_dean")
    assert iid and et_id
    _upsert_rule(
        db_conn,
        catalog_version=QAA_INST_CATALOG,
        indicator_id=iid,
        evidence_type_id=et_id,
        link_mode="evidence",
        is_required=True,
        notes_ar="مقترح تلقائي من نص المؤشر: حوكمة",
        config={"survey_template": "faculty_dean"},
    )
    n = deactivate_auto_seeded_evidence_rules(db_conn, QAA_INST_CATALOG)
    assert n >= 1
    cur = db_conn.cursor()
    active = cur.execute(
        """
        SELECT COUNT(*) FROM accreditation_indicator_evidence_rules
        WHERE catalog_version = ? AND indicator_id = ? AND COALESCE(is_active, 1) = 1
        """,
        (QAA_INST_CATALOG, iid),
    ).fetchone()[0]
    assert int(active) == 0


def test_bindable_sources_freeform_after_deactivate(db_conn):
    ensure_qaa_catalog(db_conn)
    ensure_evidence_rules_for_catalog(db_conn, QAA_INST_CATALOG)
    cur = db_conn.cursor()
    ind = cur.execute(
        """
        SELECT i.id FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE s.catalog_version = ? AND i.code = 'INST-02-01'
        LIMIT 1
        """,
        (QAA_INST_CATALOG,),
    ).fetchone()[0]
    rules = list_evidence_rules(
        db_conn, catalog_version=QAA_INST_CATALOG, indicator_id=int(ind)
    )
    assert rules == []
    data = build_bindable_sources(
        db_conn,
        indicator_id=int(ind),
        semester="manual-sem",
        catalog_version=QAA_INST_CATALOG,
    )
    assert data.get("freeform_mode") is True
    assert data.get("expected_evidence") == []
    assert len(data.get("sources", {}).get("surveys") or []) >= 1


def test_save_freeform_survey_binding(db_conn):
    ensure_qaa_catalog(db_conn)
    ensure_evidence_rules_for_catalog(db_conn, QAA_INST_CATALOG)
    cur = db_conn.cursor()
    ind = cur.execute(
        """
        SELECT i.id FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE s.catalog_version = ? LIMIT 1
        """,
        (QAA_INST_CATALOG,),
    ).fetchone()[0]
    result = save_binding(
        db_conn,
        {
            "semester": "manual-sem",
            "indicator_id": int(ind),
            "binding_kind": "survey",
            "source_ref": "survey:student_course",
            "label_ar": "استبيان المقرر",
        },
        actor="test",
    )
    assert result["status"] == "ok"
    assert result["id"] > 0
