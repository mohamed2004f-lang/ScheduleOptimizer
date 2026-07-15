"""اختبارات الاعتماد المؤسسي (هـ-1) — مسار QAA التشغيلي."""

from backend.core.accreditation_catalog import (
    QAA_INST_CATALOG_VERSION,
    ensure_accreditation_catalog,
    seed_internal_accreditation_catalog,
)
from backend.services.institutional_accreditation import build_compliance_map


def test_ensure_accreditation_catalog_seeds_qaa(db_conn):
    stats = ensure_accreditation_catalog(db_conn)
    assert stats["catalog_version"] == QAA_INST_CATALOG_VERSION
    cur = db_conn.cursor()
    n_std = cur.execute(
        "SELECT COUNT(*) FROM accreditation_standards WHERE catalog_version = ?",
        (QAA_INST_CATALOG_VERSION,),
    ).fetchone()[0]
    assert int(n_std) >= 1


def test_build_compliance_map_structure(db_conn):
    ensure_accreditation_catalog(db_conn)
    data = build_compliance_map(
        db_conn,
        semester="1447-1",
        department_id=None,
        catalog_version=QAA_INST_CATALOG_VERSION,
        ensure_seed=False,
    )
    assert data["status"] == "ok"
    assert len(data["domains"]) >= 1
    assert data["summary"]["indicators_total"] >= 100
    first_ind = None
    for dom in data["domains"]:
        for st in dom.get("standards") or []:
            if st.get("indicators"):
                first_ind = st["indicators"][0]
                break
        if first_ind:
            break
    assert first_ind is not None
    cov = first_ind.get("evidence_coverage")
    if cov:
        assert "label_ar" in cov
        assert "bound" in cov
        assert "rules_total" in cov


def test_accreditation_map_page_and_assessment(app, db_conn, auth_client):
    ensure_accreditation_catalog(db_conn)
    page = auth_client.get("/academic_quality/accreditation/map")
    assert page.status_code == 200
    assert "خريطة امتثال".encode("utf-8") in page.data or b"accreditation" in page.data.lower()
    assert b"2026.1" not in page.data or "أرشيف".encode("utf-8") in page.data

    api = auth_client.get("/academic_quality/api/accreditation/compliance_map?semester=test-sem&scope=inst")
    assert api.status_code == 200
    body = api.get_json() or {}
    assert (body.get("summary") or {}).get("indicators_total", 0) >= 100
    assert body.get("catalog_version") == QAA_INST_CATALOG_VERSION

    ind_id = db_conn.cursor().execute(
        """
        SELECT i.id FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE s.catalog_version = ?
        ORDER BY i.id LIMIT 1
        """,
        (QAA_INST_CATALOG_VERSION,),
    ).fetchone()[0]
    save = auth_client.post(
        "/academic_quality/api/accreditation/assessment/save",
        json={
            "semester": "test-sem",
            "scope": "inst",
            "catalog_version": QAA_INST_CATALOG_VERSION,
            "indicator_id": int(ind_id),
            "compliance_status": "in_progress",
            "score_percent": 55,
            "notes": "اختبار هـ-1",
        },
    )
    assert save.status_code == 200


def test_internal_seed_helper_for_legacy_tests(db_conn):
    seed_internal_accreditation_catalog(db_conn)
    data = build_compliance_map(
        db_conn,
        semester="legacy-sem",
        department_id=None,
        catalog_version="2026.1",
        ensure_seed=False,
    )
    assert data["summary"]["indicators_total"] >= 15
