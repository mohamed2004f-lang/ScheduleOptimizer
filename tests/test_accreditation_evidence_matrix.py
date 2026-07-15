"""اختبارات مصفوفة أدلة الاعتماد — المرحلة أ."""

from backend.core.accreditation_catalog import CATALOG_VERSION, ensure_accreditation_catalog
from backend.core.accreditation_evidence_rules_seed import ensure_evidence_types
from backend.services.accreditation_evidence_matrix import (
    build_evidence_matrix,
    ensure_evidence_binding_schema,
    list_evidence_types,
    save_evidence_rule,
)


def test_evidence_types_seeded(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    ensure_evidence_binding_schema(db_conn)
    types = list_evidence_types(db_conn)
    assert len(types) >= 15
    codes = {t["code"] for t in types}
    assert "survey_student_course" in codes
    assert "minutes_qa_committee" in codes


def test_evidence_matrix_qaa_manual_rule_only(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    ensure_evidence_binding_schema(db_conn)
    cur = db_conn.cursor()
    ind = cur.execute(
        """
        SELECT i.id FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE s.catalog_version = 'QAA-2023.4-INST'
        LIMIT 1
        """
    ).fetchone()[0]
    save_evidence_rule(
        db_conn,
        {
            "catalog_version": "QAA-2023.4-INST",
            "indicator_id": int(ind),
            "evidence_type_code": "minutes_qa_committee",
            "link_mode": "evidence",
            "is_required": False,
            "notes_ar": "قاعدة يدوية من المسؤول",
        },
        actor="test",
    )
    data = build_evidence_matrix(
        db_conn,
        semester="ev-matrix-sem",
        department_id=None,
        catalog_version="QAA-2023.4-INST",
    )
    assert data["status"] == "ok"
    assert data["summary"]["total"] >= 1
    row = data["rows"][0]
    assert "link_mode_label" in row
    assert "fulfillment" in row
    assert row["fulfillment"]["status"] in ("met", "partial", "missing", "not_applicable")


def test_evidence_matrix_internal_catalog(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    ensure_evidence_binding_schema(db_conn)
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
            "evidence_type_code": "generic_file_upload",
            "link_mode": "evidence",
            "is_required": False,
            "notes_ar": "قاعدة يدوية",
        },
        actor="test",
    )
    data = build_evidence_matrix(
        db_conn,
        semester="ev-matrix-sem2",
        department_id=None,
        catalog_version=CATALOG_VERSION,
    )
    assert data["status"] == "ok"
    assert data["summary"]["total"] >= 1


def test_save_evidence_rule(db_conn):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    ensure_evidence_binding_schema(db_conn)
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
    result = save_evidence_rule(
        db_conn,
        {
            "catalog_version": CATALOG_VERSION,
            "indicator_id": int(ind),
            "evidence_type_code": "minutes_qa_committee",
            "link_mode": "evidence",
            "is_required": True,
            "notes_ar": "اختبار قاعدة ربط",
        },
        actor="test",
    )
    assert result["status"] == "ok"
    assert result["id"] > 0


def test_evidence_matrix_api(app, db_conn, auth_client):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    r = auth_client.get(
        "/academic_quality/api/accreditation/evidence/matrix?semester=api-ev-mx&catalog_version=QAA-2023.4-INST"
    )
    assert r.status_code == 200
    body = r.get_json() or {}
    assert body.get("status") == "ok"
    assert isinstance((body.get("summary") or {}).get("total"), int)

    types = auth_client.get("/academic_quality/api/accreditation/evidence/types")
    assert types.status_code == 200
    assert len((types.get_json() or {}).get("items") or []) >= 15

    perms = auth_client.get("/academic_quality/api/accreditation/evidence/permissions")
    assert perms.status_code == 200
    assert (perms.get_json() or {}).get("can_edit_catalog") is True

    save_type = auth_client.post(
        "/academic_quality/api/accreditation/evidence/types",
        json={
            "code": "custom_test_evidence",
            "title_ar": "دليل اختباري مخصص",
            "category": "file",
            "description_ar": "للاختبار",
            "sort_order": 900,
        },
    )
    assert save_type.status_code == 200
    type_id = (save_type.get_json() or {}).get("id")
    assert type_id

    indicators = auth_client.get(
        "/academic_quality/api/accreditation/evidence/indicators?catalog_version="
        + CATALOG_VERSION
    )
    assert indicators.status_code == 200
    ind_items = (indicators.get_json() or {}).get("items") or []
    assert len(ind_items) >= 1

    save_rule = auth_client.post(
        "/academic_quality/api/accreditation/evidence/rules",
        json={
            "catalog_version": CATALOG_VERSION,
            "indicator_id": ind_items[0]["id"],
            "evidence_type_code": "custom_test_evidence",
            "link_mode": "evidence",
            "is_required": False,
            "notes_ar": "قاعدة اختبار ب1",
        },
    )
    assert save_rule.status_code == 200

    delete_type = auth_client.delete(
        f"/academic_quality/api/accreditation/evidence/types/{type_id}"
    )
    assert delete_type.status_code == 200


def test_catalog_editor_forbidden_for_hod(app, db_conn, client):
    ensure_accreditation_catalog(db_conn, seed_internal=True)
    ensure_evidence_binding_schema(db_conn)
    from backend.core.auth import hash_password

    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO users (username, password_hash, role, is_active)
        VALUES (?, ?, 'head_of_department', 1)
        """,
        ("hod-ev-test", hash_password("TestP@ssw0rd!")),
    )
    db_conn.commit()
    client.post("/auth/login", json={"username": "hod-ev-test", "password": "TestP@ssw0rd!"})
    r = client.post(
        "/academic_quality/api/accreditation/evidence/types",
        json={"code": "hod_should_fail", "title_ar": "x", "category": "file"},
    )
    assert r.status_code == 403
