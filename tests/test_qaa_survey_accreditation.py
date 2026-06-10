"""اختبارات سياسة ربط الاستبيانات — يدوي فقط (بدون آلي/إلزامي)."""

from backend.core.accreditation_evidence_rules_seed import (
    demote_qaa_survey_auto_rules,
    ensure_evidence_rules_for_catalog,
    seed_qaa_survey_map_rules,
)
from backend.core.qaa_catalog_seed import ensure_qaa_catalog
from backend.core.qaa_survey_accreditation_map import (
    QAA_INST_CATALOG,
    QAA_PROG_UG_CATALOG,
    qaa_links_for_template,
)
from backend.services.survey_accreditation_links import (
    primary_evidence_indicator_code_resolved,
    resolve_survey_accreditation_links,
)


def test_qaa_survey_map_links_are_evidence_not_auto():
    for tpl in ("student_course", "student_facilities"):
        for lk in qaa_links_for_template(tpl):
            assert lk.get("link_type") != "auto"


def test_demote_qaa_survey_auto_rules(db_conn):
    ensure_qaa_catalog(db_conn)
    seed_qaa_survey_map_rules(db_conn, QAA_INST_CATALOG, force=True)
    n = demote_qaa_survey_auto_rules(db_conn, QAA_INST_CATALOG)
    assert n >= 1
    cur = db_conn.cursor()
    row = cur.execute(
        """
        SELECT link_mode, is_required FROM accreditation_indicator_evidence_rules r
        INNER JOIN accreditation_indicators i ON i.id = r.indicator_id
        WHERE r.catalog_version = ? AND i.code = 'INST-09-15'
          AND r.config_json LIKE ?
        LIMIT 1
        """,
        (QAA_INST_CATALOG, '%"survey_template": "student_course"%'),
    ).fetchone()
    assert row is not None
    assert row[0] == "evidence"
    assert int(row[1]) == 0


def test_ensure_catalog_demotes_without_new_auto_seed(db_conn):
    ensure_qaa_catalog(db_conn)
    ensure_evidence_rules_for_catalog(db_conn, QAA_INST_CATALOG)
    cur = db_conn.cursor()
    auto_n = cur.execute(
        """
        SELECT COUNT(*) FROM accreditation_indicator_evidence_rules
        WHERE catalog_version = ? AND link_mode = 'auto'
          AND config_json LIKE '%survey_template%'
          AND COALESCE(is_active, 1) = 1
        """,
        (QAA_INST_CATALOG,),
    ).fetchone()[0]
    assert int(auto_n) == 0


def test_resolve_survey_links_empty_when_no_manual_rules(db_conn):
    ensure_qaa_catalog(db_conn)
    ensure_evidence_rules_for_catalog(db_conn, QAA_INST_CATALOG)
    links = resolve_survey_accreditation_links(
        db_conn, "student_course", catalog_version=QAA_INST_CATALOG
    )
    assert links == [] or all(lk.get("link_type") != "auto" for lk in links)


def test_primary_indicator_not_internal_when_qaa_active(db_conn):
    ensure_qaa_catalog(db_conn)
    ensure_evidence_rules_for_catalog(db_conn, QAA_INST_CATALOG)
    code = primary_evidence_indicator_code_resolved(
        db_conn, "student_course", catalog_version=QAA_INST_CATALOG
    )
    if code:
        assert not code.startswith("SS-")
        assert not code.startswith("GV-")
