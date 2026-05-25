"""اختبارات بوابة هوية الكلية والبرامج."""

from backend.core.college_identity_schema import ensure_college_identity_schema
from backend.core.college_identity_seed import DEFAULT_MISSION_AR
from backend.core.plo_schema import ensure_plo_enhancement_schema
from backend.services.college_identity_portal import college_profile_payload, program_profile_payload


def test_college_identity_seed_and_profile(db_conn):
    ensure_plo_enhancement_schema(db_conn)
    payload = college_profile_payload(db_conn)
    assert payload.get("identity")
    assert (payload["identity"].get("mission_ar") or "") == DEFAULT_MISSION_AR
    assert len(payload.get("goals_tree") or []) >= 8
    assert len(payload.get("glos") or []) >= 8
    assert len(payload.get("kpis") or []) >= 1


def test_college_api(auth_client, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    db_conn.commit()
    r = auth_client.get("/academic_quality/api/college/profile")
    assert r.status_code == 200
    j = r.get_json() or {}
    assert j.get("status") == "ok"
    assert j.get("identity", {}).get("mission_ar")


def test_college_page(auth_client):
    r = auth_client.get("/academic_quality/college")
    assert r.status_code == 200


def test_programs_list_api(auth_client, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    db_conn.commit()
    r = auth_client.get("/academic_quality/api/programs/list")
    assert r.status_code == 200
    assert (r.get_json() or {}).get("status") == "ok"


def test_college_values_and_ig_crud(auth_client, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    db_conn.commit()
    r = auth_client.put(
        "/academic_quality/api/college/values",
        json={
            "values": [
                {"code": "CV_TEST", "title_ar": "قيمة اختبار", "description": "وصف"},
            ]
        },
    )
    assert r.status_code == 200
    r2 = auth_client.post(
        "/academic_quality/api/college/strategic-goals",
        json={"code": "IG_TEST", "title_ar": "هدف اختبار", "sort_order": 99},
    )
    assert r2.status_code == 200
    r3 = auth_client.delete("/academic_quality/api/college/strategic-goals/IG_TEST")
    assert r3.status_code == 200


def test_program_profile_if_program_exists(auth_client, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    row = db_conn.cursor().execute(
        "SELECT id FROM programs WHERE COALESCE(is_active,1)=1 LIMIT 1"
    ).fetchone()
    if not row:
        return
    pid = int(row[0] if not hasattr(row, "keys") else row["id"])
    payload = program_profile_payload(db_conn, pid)
    assert payload.get("program")
    r = auth_client.get(f"/academic_quality/api/programs/{pid}/profile")
    assert r.status_code == 200
