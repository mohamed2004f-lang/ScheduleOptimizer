"""اختبارات بوابة هوية الكلية والبرامج."""

from backend.core.college_identity_schema import (
    ensure_college_identity_schema,
    is_college_identity_seed_locked,
    set_college_identity_seed_locked,
)
from backend.core.college_identity_seed import DEFAULT_MISSION_AR
from backend.core.plo_schema import ensure_plo_enhancement_schema
from backend.services.college_identity_portal import (
    build_college_story_payload,
    college_profile_payload,
    program_profile_payload,
)


def _login_as(client, username: str, password: str = "TestP@ssw0rd!") -> None:
    with client.session_transaction() as sess:
        sess.clear()
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed for {username}: {resp.get_data(as_text=True)}"


def _ensure_editor_user(db_conn, username: str = "dean-identity", role: str = "college_dean") -> None:
    try:
        from werkzeug.security import generate_password_hash

        pw = generate_password_hash("TestP@ssw0rd!")
    except ImportError:
        from backend.core.auth import hash_password

        pw = hash_password("TestP@ssw0rd!")
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role, is_system_account)
        VALUES (?, ?, ?, 0)
        ON CONFLICT(username) DO UPDATE SET role=excluded.role, password_hash=excluded.password_hash
        """,
        (username, pw, role),
    )
    try:
        db_conn.commit()
    except Exception:
        pass


def test_college_identity_seed_and_profile(db_conn):
    ensure_plo_enhancement_schema(db_conn)
    payload = college_profile_payload(db_conn)
    assert payload.get("identity")
    assert (payload["identity"].get("mission_ar") or "") == DEFAULT_MISSION_AR
    assert len(payload.get("goals_tree") or []) >= 8
    assert len(payload.get("glos") or []) >= 8
    assert len(payload.get("kpis") or []) >= 1


def test_college_story_payload_without_kpi_by_default(db_conn):
    ensure_plo_enhancement_schema(db_conn)
    story = build_college_story_payload(db_conn, include_kpi=False)
    assert story["college"].get("mission_ar")
    assert story["college"].get("vision_ar")
    assert "kpis" not in story["college"]
    # القصة تعرض الجذور فقط (مثلاً IG1…IG8) دون الفروع IG1.1…
    goals = story["college"].get("goals") or []
    assert 8 <= len(goals) <= 12
    assert all("." not in (g.get("code") or "") for g in goals)
    with_kpi = build_college_story_payload(db_conn, include_kpi=True)
    assert "kpis" in with_kpi["college"]
    full = build_college_story_payload(db_conn, include_kpi=False, goals_roots_only=False)
    assert len(full["college"].get("goals") or []) >= len(goals)


def test_college_api(auth_client, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    db_conn.commit()
    r = auth_client.get("/academic_quality/api/college/profile")
    assert r.status_code == 200
    j = r.get_json() or {}
    assert j.get("status") == "ok"
    assert j.get("identity", {}).get("mission_ar")
    # system_admin يقرأ ولا يحرّر
    assert j.get("can_edit") is False


def test_college_page(auth_client):
    r = auth_client.get("/academic_quality/college")
    assert r.status_code == 200


def test_instructor_redirected_from_college_workshop(instructor_auth_client):
    r = instructor_auth_client.get("/academic_quality/college", follow_redirects=False)
    assert r.status_code in (301, 302)
    assert "/outcomes-map" in (r.headers.get("Location") or "")


def test_programs_list_api(auth_client, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    db_conn.commit()
    r = auth_client.get("/academic_quality/api/programs/list")
    assert r.status_code == 200
    assert (r.get_json() or {}).get("status") == "ok"


def test_college_values_and_ig_crud(app, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    _ensure_editor_user(db_conn, "dean-identity", "college_dean")
    db_conn.commit()
    with app.test_client() as client:
        _login_as(client, "dean-identity")
        r = client.put(
            "/academic_quality/api/college/values",
            json={
                "values": [
                    {"code": "CV_TEST", "title_ar": "قيمة اختبار", "description": "وصف"},
                ]
            },
        )
        assert r.status_code == 200
        r2 = client.post(
            "/academic_quality/api/college/strategic-goals",
            json={"code": "IG_TEST", "title_ar": "هدف اختبار", "sort_order": 99},
        )
        assert r2.status_code == 200
        r3 = client.delete("/academic_quality/api/college/strategic-goals/IG_TEST")
        assert r3.status_code == 200


def test_system_admin_cannot_edit_identity(auth_client, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    db_conn.commit()
    # إعادة جلسة system_admin لأن auth_client مشترك على مستوى الجلسة
    _login_as(auth_client, "admin-test")
    r = auth_client.put(
        "/academic_quality/api/college/identity",
        json={"mission_ar": "لا يجب", "vision_ar": "لا يجب"},
    )
    assert r.status_code == 403


def test_comment_flow_vice_dean_and_dean(app, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    ensure_college_identity_schema(db_conn)
    _ensure_editor_user(db_conn, "vd-identity", "academic_vice_dean")
    _ensure_editor_user(db_conn, "dean-cmt", "college_dean")
    db_conn.commit()
    with app.test_client() as client:
        _login_as(client, "vd-identity")
        r = client.post(
            "/academic_quality/api/college/comments",
            json={
                "target_type": "identity_field",
                "target_key": "mission_ar",
                "body_ar": "اقتراح تحسين الرسالة",
            },
        )
        assert r.status_code == 200
        cid = (r.get_json() or {}).get("id")
        assert cid
        r_bad = client.put(
            f"/academic_quality/api/college/comments/{cid}",
            json={"status": "accepted"},
        )
        assert r_bad.status_code == 403
        _login_as(client, "dean-cmt")
        r2 = client.put(
            f"/academic_quality/api/college/comments/{cid}",
            json={"status": "accepted", "dean_reply_ar": "مقبول"},
        )
        assert r2.status_code == 200


def test_outcomes_map_story_for_instructor(instructor_auth_client, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    db_conn.commit()
    r = instructor_auth_client.get("/academic_quality/ilo/api/outcomes-map")
    assert r.status_code == 200
    j = r.get_json() or {}
    assert j.get("status") == "ok"
    assert j.get("college", {}).get("vision_ar") is not None
    assert "kpis" not in (j.get("college") or {})


def test_purge_locks_seed(app, db_conn):
    ensure_plo_enhancement_schema(db_conn)
    ensure_college_identity_schema(db_conn)
    _ensure_editor_user(db_conn, "dean-purge", "college_dean")
    db_conn.commit()
    with app.test_client() as client:
        _login_as(client, "dean-purge")
        r = client.post(
            "/academic_quality/api/college/purge-operational",
            json={"confirm": True},
        )
        assert r.status_code == 200
        body = r.get_json() or {}
        assert body.get("seed_locked") is True
    assert is_college_identity_seed_locked(db_conn) is True
    before = db_conn.cursor().execute(
        "SELECT COUNT(*) FROM college_strategic_goals WHERE COALESCE(is_active,1)=1"
    ).fetchone()[0]
    ensure_college_identity_schema(db_conn)
    after = db_conn.cursor().execute(
        "SELECT COUNT(*) FROM college_strategic_goals WHERE COALESCE(is_active,1)=1"
    ).fetchone()[0]
    assert int(after) == int(before)
    set_college_identity_seed_locked(db_conn, False)
    db_conn.commit()


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
