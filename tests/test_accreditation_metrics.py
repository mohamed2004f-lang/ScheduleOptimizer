"""اختبارات حساب مؤشرات الاعتماد الآلي (هـ-2)."""

from backend.core.accreditation_catalog import ensure_accreditation_catalog
from backend.services.accreditation_metrics import (
    AUTO_INDICATOR_CODES,
    apply_auto_assessments,
    compute_indicator_auto,
)
from backend.services.institutional_accreditation import build_compliance_map


def test_compute_hr01_auto(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO instructors (name, type, is_active, department_id)
        VALUES ('أ. اختبار', 'internal', 1, NULL)
        """
    )
    db_conn.commit()
    out = compute_indicator_auto(db_conn, "HR-01-1", semester="test-h2", department_id=None)
    assert out["indicator_code"] == "HR-01-1"
    assert out.get("score_percent") is not None
    assert out["compliance_status"] in ("met", "partial", "gap", "in_progress")


def test_apply_auto_assessments_updates_map(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    result = apply_auto_assessments(
        db_conn,
        semester="test-h2-auto",
        department_id=None,
        actor="pytest",
        only_not_started=True,
        catalog_version="2026.1",
    )
    assert result["status"] == "ok"
    assert result["updated_count"] >= 1
    assert len(AUTO_INDICATOR_CODES) >= 8

    data = build_compliance_map(
        db_conn,
        semester="test-h2-auto",
        department_id=None,
        catalog_version="2026.1",
        ensure_seed=False,
    )
    auto_found = 0
    for dom in data["domains"]:
        for st in dom["standards"]:
            for ind in st["indicators"]:
                if ind["code"] in AUTO_INDICATOR_CODES:
                    if ind["assessment"]["compliance_status"] != "not_started":
                        auto_found += 1
    assert auto_found >= 1


def test_compute_auto_api(app, db_conn, auth_client):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    r = auth_client.post(
        "/academic_quality/api/accreditation/compute_auto",
        json={"semester": "api-h2", "only_not_started": True},
    )
    assert r.status_code == 200
    body = r.get_json() or {}
    assert body.get("updated_count", 0) >= 0

    meta = auth_client.get("/academic_quality/api/accreditation/meta")
    assert meta.status_code == 200
    assert "qaa_higher_ed_url" in (meta.get_json() or {})
