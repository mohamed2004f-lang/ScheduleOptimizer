"""اختبارات ربط أدلة الاعتماد — المرحلة ب2–ب3."""

from backend.core.accreditation_catalog import CATALOG_VERSION, ensure_accreditation_catalog
from backend.services.accreditation_evidence_bindings import (
    build_bindable_sources,
    ensure_bindings_schema,
    list_bindings,
    save_binding,
)
from backend.services.accreditation_evidence_matrix import (
    ensure_evidence_binding_schema,
    save_evidence_rule,
)


def test_bindable_sources_has_expected_and_surveys(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    ensure_evidence_binding_schema(db_conn)
    ensure_bindings_schema(db_conn)
    cur = db_conn.cursor()
    ind = cur.execute(
        """
        SELECT i.id FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE s.catalog_version = ?
        LIMIT 1
        """,
        (CATALOG_VERSION,),
    ).fetchone()[0]
    data = build_bindable_sources(
        db_conn,
        indicator_id=int(ind),
        semester="bind-sem",
        department_id=None,
        catalog_version=CATALOG_VERSION,
    )
    assert data["status"] == "ok"
    assert isinstance(data.get("expected_evidence"), list)
    assert "surveys" in data.get("sources", {})
    assert "witnesses" in data.get("sources", {})
    assert "reports" in data.get("sources", {})


def test_save_binding_witness(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    ensure_evidence_binding_schema(db_conn)
    ensure_bindings_schema(db_conn)
    cur = db_conn.cursor()
    ind = cur.execute(
        """
        SELECT i.id FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE s.catalog_version = ?
        LIMIT 1
        """,
        (CATALOG_VERSION,),
    ).fetchone()[0]
    save_evidence_rule(
        db_conn,
        {
            "catalog_version": CATALOG_VERSION,
            "indicator_id": int(ind),
            "evidence_type_code": "minutes_qa_committee",
            "link_mode": "evidence",
            "is_required": True,
        },
        actor="test",
    )
    cur.execute(
        """
        SELECT id FROM accreditation_evidence_types
        WHERE code = 'minutes_qa_committee' LIMIT 1
        """
    )
    et_id = int(cur.fetchone()[0])
    from backend.services.accreditation_evidence import save_link_evidence

    ev = save_link_evidence(
        db_conn,
        semester="bind-sem",
        department_id=None,
        indicator_id=int(ind),
        external_url="https://example.com/witness.pdf",
        title_ar="شاهد اختبار",
        uploaded_by="test",
    )
    result = save_binding(
        db_conn,
        {
            "semester": "bind-sem",
            "department_id": None,
            "indicator_id": int(ind),
            "evidence_type_id": et_id,
            "binding_kind": "witness",
            "source_ref": f"witness:{ev['id']}",
            "label_ar": "شاهد اختبار",
        },
        actor="test",
    )
    assert result["status"] == "ok"
    assert result["id"] > 0
    items = list_bindings(
        db_conn, semester="bind-sem", department_id=None, indicator_id=int(ind)
    )
    assert len(items) >= 1
    assert items[0]["binding_kind"] == "witness"


def test_bindable_sources_api(app, db_conn, auth_client):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    ensure_bindings_schema(db_conn)
    cur = db_conn.cursor()
    ind = cur.execute(
        """
        SELECT i.id FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE s.catalog_version = ?
        LIMIT 1
        """,
        (CATALOG_VERSION,),
    ).fetchone()[0]
    r = auth_client.get(
        "/academic_quality/api/accreditation/evidence/bindable-sources?"
        f"indicator_id={int(ind)}&semester=bind-api-sem&catalog_version={CATALOG_VERSION}"
    )
    assert r.status_code == 200
    body = r.get_json() or {}
    assert body.get("status") == "ok"
    assert body.get("indicator_id") == int(ind)

    perms = auth_client.get("/academic_quality/api/accreditation/evidence/permissions")
    assert perms.status_code == 200
    assert (perms.get_json() or {}).get("can_bind_sources") is True
