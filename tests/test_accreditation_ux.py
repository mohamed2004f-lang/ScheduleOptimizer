"""اختبارات تحسينات واجهة الاعتماد (فلتر، إصدارات)."""

from backend.core.accreditation_catalog import ensure_accreditation_catalog, list_active_catalog_versions
from backend.services.institutional_accreditation import build_compliance_map


def test_list_active_catalog_versions(db_conn):
    ensure_accreditation_catalog(db_conn)
    versions = list_active_catalog_versions(db_conn)
    assert "2026.1" in versions


def test_compliance_map_catalog_version_param(db_conn):
    ensure_accreditation_catalog(db_conn)
    data = build_compliance_map(
        db_conn, semester="v-sem", department_id=None, catalog_version="2026.1", ensure_seed=False
    )
    assert data["catalog_version"] == "2026.1"
    assert data["summary"]["indicators_total"] >= 15


def test_catalog_versions_api(app, auth_client):
    r = auth_client.get("/academic_quality/api/accreditation/catalog_versions")
    assert r.status_code == 200
    body = r.get_json() or {}
    assert "2026.1" in (body.get("versions") or [])
