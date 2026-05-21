"""اختبارات أدلة الاعتماد المؤسسي (هـ-3)."""

import io

from backend.core.accreditation_catalog import ensure_accreditation_catalog
from backend.services.accreditation_evidence import (
    build_checklist_status,
    evidence_counts_by_indicator,
    list_evidence,
    save_file_evidence,
    save_link_evidence,
    soft_delete_evidence,
)
from backend.services.institutional_accreditation import build_compliance_map


def test_build_checklist_status_empty(db_conn):
    ensure_accreditation_catalog(db_conn)
    items = build_checklist_status(db_conn, "ev-sem", None)
    assert len(items) >= 6
    assert all("checklist_key" in x and "has_evidence" in x for x in items)
    assert not any(x["has_evidence"] for x in items)


def test_evidence_upload_link_and_map_count(db_conn):
    ensure_accreditation_catalog(db_conn)
    cur = db_conn.cursor()
    ind_id = cur.execute(
        "SELECT id FROM accreditation_indicators ORDER BY id LIMIT 1"
    ).fetchone()[0]

    pdf = b"%PDF-1.4 test evidence"
    saved = save_file_evidence(
        db_conn,
        semester="ev-sem",
        department_id=None,
        raw=pdf,
        original_name="proof.pdf",
        mime_type="application/pdf",
        uploaded_by="tester",
        indicator_id=int(ind_id),
        title_ar="دليل اختبار",
    )
    assert saved["id"] > 0

    save_link_evidence(
        db_conn,
        semester="ev-sem",
        department_id=None,
        external_url="https://qaa.ly/example",
        uploaded_by="tester",
        checklist_key="self_study",
        title_ar="رابط دراسة ذاتية",
    )

    items = list_evidence(db_conn, semester="ev-sem", department_id=None)
    assert len(items) >= 2

    counts = evidence_counts_by_indicator(db_conn, "ev-sem", None)
    assert counts.get(int(ind_id), 0) >= 1

    data = build_compliance_map(db_conn, semester="ev-sem", department_id=None, ensure_seed=False)
    found = False
    for dom in data.get("domains") or []:
        for st in dom.get("standards") or []:
            for ind in st.get("indicators") or []:
                if int(ind["id"]) == int(ind_id):
                    assert ind.get("evidence_count", 0) >= 1
                    found = True
    assert found

    checklist = build_checklist_status(db_conn, "ev-sem", None)
    self_study = next(x for x in checklist if x["checklist_key"] == "self_study")
    assert self_study["has_evidence"]

    assert soft_delete_evidence(db_conn, saved["id"])


def test_evidence_api_routes(app, db_conn, auth_client):
    ensure_accreditation_catalog(db_conn)
    ind_id = db_conn.cursor().execute(
        "SELECT id FROM accreditation_indicators ORDER BY id LIMIT 1"
    ).fetchone()[0]

    chk = auth_client.get(
        "/academic_quality/api/accreditation/evidence/checklist?semester=api-ev"
    )
    assert chk.status_code == 200
    assert len((chk.get_json() or {}).get("items") or []) >= 6

    data = {
        "semester": "api-ev",
        "indicator_id": int(ind_id),
        "external_url": "https://example.com/policy",
        "title_ar": "سياسة",
    }
    link = auth_client.post(
        "/academic_quality/api/accreditation/evidence/link",
        json=data,
    )
    assert link.status_code == 200

    lst = auth_client.get(
        f"/academic_quality/api/accreditation/evidence/list?semester=api-ev&indicator_id={ind_id}"
    )
    assert lst.status_code == 200
    items = (lst.get_json() or {}).get("items") or []
    assert len(items) >= 1
    eid = items[0]["id"]

    buf2 = io.BytesIO(b"%PDF-1.4 api upload")
    up = auth_client.post(
        "/academic_quality/api/accreditation/evidence/upload",
        data={
            "semester": "api-ev",
            "indicator_id": str(ind_id),
            "file": (buf2, "doc.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert up.status_code == 200
    file_id = (up.get_json() or {}).get("id")
    if file_id:
        dl = auth_client.get(f"/academic_quality/api/accreditation/evidence/file/{file_id}")
        assert dl.status_code == 200

    rm = auth_client.delete(f"/academic_quality/api/accreditation/evidence/{eid}")
    assert rm.status_code == 200
