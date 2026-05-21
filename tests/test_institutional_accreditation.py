"""اختبارات الاعتماد المؤسسي (هـ-1)."""

from backend.core.accreditation_catalog import (
    CATALOG_VERSION,
    ensure_accreditation_catalog,
)
from backend.services.institutional_accreditation import build_compliance_map


def test_ensure_accreditation_catalog_seeds(db_conn):
    stats = ensure_accreditation_catalog(db_conn)
    assert stats["catalog_version"] == CATALOG_VERSION
    cur = db_conn.cursor()
    n_std = cur.execute(
        "SELECT COUNT(*) FROM accreditation_standards WHERE catalog_version = ?",
        (CATALOG_VERSION,),
    ).fetchone()[0]
    n_ind = cur.execute("SELECT COUNT(*) FROM accreditation_indicators").fetchone()[0]
    assert int(n_std) >= 15
    assert int(n_ind) >= 15


def test_build_compliance_map_structure(db_conn):
    ensure_accreditation_catalog(db_conn)
    data = build_compliance_map(db_conn, semester="1447-1", department_id=None, ensure_seed=False)
    assert data["status"] == "ok"
    assert len(data["domains"]) >= 7
    assert data["summary"]["indicators_total"] >= 15
    assert data["summary"]["not_started"] >= 1


def test_accreditation_map_page_and_assessment(app, db_conn, auth_client):
    ensure_accreditation_catalog(db_conn)
    page = auth_client.get("/academic_quality/accreditation/map")
    assert page.status_code == 200
    assert "خريطة امتثال".encode("utf-8") in page.data or b"accreditation" in page.data.lower()

    api = auth_client.get("/academic_quality/api/accreditation/compliance_map?semester=test-sem")
    assert api.status_code == 200
    body = api.get_json() or {}
    assert (body.get("summary") or {}).get("indicators_total", 0) >= 15

    ind_id = db_conn.cursor().execute(
        "SELECT id FROM accreditation_indicators ORDER BY id LIMIT 1"
    ).fetchone()[0]
    save = auth_client.post(
        "/academic_quality/api/accreditation/assessment/save",
        json={
            "semester": "test-sem",
            "indicator_id": int(ind_id),
            "compliance_status": "in_progress",
            "score_percent": 55,
            "notes": "اختبار هـ-1",
        },
    )
    assert save.status_code == 200

    data = build_compliance_map(db_conn, semester="test-sem", department_id=None, ensure_seed=False)
    found = False
    for dom in data.get("domains") or []:
        for st in dom.get("standards") or []:
            for ind in st.get("indicators") or []:
                if int(ind["id"]) == int(ind_id):
                    assert ind["assessment"]["compliance_status"] == "in_progress"
                    found = True
    assert found
