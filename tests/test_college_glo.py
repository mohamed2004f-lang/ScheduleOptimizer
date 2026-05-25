"""اختبارات مخرجات الكلية (GLO) — CRUD."""

from backend.core.plo_glo import seed_college_glo_defaults
from backend.core.plo_schema import ensure_plo_enhancement_schema


def test_glo_seed_and_list(db_conn):
    ensure_plo_enhancement_schema(db_conn)
    seed_college_glo_defaults(db_conn)
    db_conn.commit()

    from backend.core.plo_glo import glo_list_from_db

    items = glo_list_from_db(db_conn, active_only=True)
    codes = {x["code"] for x in items}
    assert "GLO1" in codes
    assert "GLO8" in codes
    assert len(items) >= 8


def test_glo_crud_api(auth_client, db_conn):
    ensure_plo_enhancement_schema(db_conn)

    r = auth_client.get("/academic_quality/ilo/api/glo")
    assert r.status_code == 200
    body = r.get_json() or {}
    assert body.get("status") == "ok"
    if not body.get("items"):
        r_seed = auth_client.post(
            "/academic_quality/ilo/api/glo",
            json={
                "code": "GLO_TEST2",
                "title_ar": "مخرج اختبار 2",
                "domain": "technical_skills",
            },
        )
        assert r_seed.status_code == 200
        body = (auth_client.get("/academic_quality/ilo/api/glo").get_json() or {})
    assert len(body.get("items") or []) >= 1

    r2 = auth_client.post(
        "/academic_quality/ilo/api/glo",
        json={
            "code": "GLO_TEST",
            "title_ar": "مخرج اختبار",
            "description": "وصف",
            "domain": "technical_skills",
            "sort_order": 999,
        },
    )
    assert r2.status_code == 200
    gid = (r2.get_json() or {}).get("id")
    assert gid

    r3 = auth_client.put(
        f"/academic_quality/ilo/api/glo/{gid}",
        json={"title_ar": "مخرج محدّث", "is_active": True},
    )
    assert r3.status_code == 200

    r4 = auth_client.delete(f"/academic_quality/ilo/api/glo/{gid}")
    assert r4.status_code == 200
