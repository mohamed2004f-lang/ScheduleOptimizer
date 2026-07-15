"""اختبارات تحسينات واجهة الاعتماد (فلتر، إصدارات)."""

from backend.core.accreditation_catalog import (
    QAA_INST_CATALOG_VERSION,
    ensure_accreditation_catalog,
    list_operational_catalog_versions,
    seed_internal_accreditation_catalog,
)
from backend.services.institutional_accreditation import build_compliance_map


def test_list_operational_catalog_versions(db_conn):
    ensure_accreditation_catalog(db_conn)
    versions = list_operational_catalog_versions(db_conn)
    assert QAA_INST_CATALOG_VERSION in versions
    assert "2026.1" not in versions


def test_compliance_map_catalog_version_param(db_conn):
    seed_internal_accreditation_catalog(db_conn)
    data = build_compliance_map(
        db_conn, semester="v-sem", department_id=None, catalog_version="2026.1", ensure_seed=False
    )
    assert data["catalog_version"] == "2026.1"
    assert data["summary"]["indicators_total"] >= 15


def test_catalog_versions_api(app, auth_client):
    r = auth_client.get("/academic_quality/api/accreditation/catalog_versions")
    assert r.status_code == 200
    body = r.get_json() or {}
    versions = body.get("versions") or []
    assert QAA_INST_CATALOG_VERSION in versions
    assert "2026.1" not in versions
