"""اختبارات مخرجات الكلية (GLO) — CRUD."""

from backend.core.plo_glo import seed_college_glo_defaults
from backend.core.plo_schema import ensure_plo_enhancement_schema


def _ensure_dean(db_conn, username: str = "dean-glo"):
    try:
        from werkzeug.security import generate_password_hash

        pw = generate_password_hash("TestP@ssw0rd!")
    except ImportError:
        from backend.core.auth import hash_password

        pw = hash_password("TestP@ssw0rd!")
    db_conn.execute(
        """
        INSERT INTO users (username, password_hash, role, is_system_account)
        VALUES (?, ?, 'college_dean', 0)
        ON CONFLICT(username) DO UPDATE SET role='college_dean', password_hash=excluded.password_hash
        """,
        (username, pw),
    )
    db_conn.commit()


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


def test_glo_crud_api(app, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    _ensure_dean(db_conn)
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess.clear()
        assert client.post(
            "/auth/login", json={"username": "dean-glo", "password": "TestP@ssw0rd!"}
        ).status_code == 200

        r = client.get("/academic_quality/ilo/api/glo")
        assert r.status_code == 200
        body = r.get_json() or {}
        assert body.get("status") == "ok"
        assert body.get("can_edit") is True
        if not body.get("items"):
            r_seed = client.post(
                "/academic_quality/ilo/api/glo",
                json={
                    "code": "GLO_TEST2",
                    "title_ar": "مخرج اختبار 2",
                    "domain": "technical_skills",
                },
            )
            assert r_seed.status_code == 200
            body = (client.get("/academic_quality/ilo/api/glo").get_json() or {})
        assert len(body.get("items") or []) >= 1

        r2 = client.post(
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

        r3 = client.put(
            f"/academic_quality/ilo/api/glo/{gid}",
            json={"title_ar": "مخرج محدّث", "is_active": True},
        )
        assert r3.status_code == 200

        r4 = client.delete(f"/academic_quality/ilo/api/glo/{gid}")
        assert r4.status_code == 200


def test_glo_system_admin_cannot_write(auth_client, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    assert auth_client.post(
        "/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"}
    ).status_code == 200
    r = auth_client.get("/academic_quality/ilo/api/glo")
    assert r.status_code == 200
    assert (r.get_json() or {}).get("can_edit") is False
    r2 = auth_client.post(
        "/academic_quality/ilo/api/glo",
        json={"code": "GLO_X", "title_ar": "x", "domain": "technical_skills"},
    )
    assert r2.status_code == 403
