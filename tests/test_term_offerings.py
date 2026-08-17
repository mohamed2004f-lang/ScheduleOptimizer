"""اعتماد عرض المقررات، قائمة التسجيل، وتفريغ جدول الفصل الحالي."""
from __future__ import annotations

import uuid

from backend.database.database import TABLES_SCHEMA
from backend.services.term_engine import (
    confirm_term_label_matches,
    current_term_match_context,
    ensure_term_engine_tables,
    parse_ops_term,
    schedule_semester_matches_term_context,
)
from backend.services.utilities import set_schedule_published_at


def _login_admin(app):
    c = app.test_client()
    resp = c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return c


def _restore_default_term(db_conn):
    db_conn.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', 'خريف')"
    )
    db_conn.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', '44-45')"
    )
    db_conn.commit()


def test_schema_includes_offering_tables():
    assert "term_course_offerings" in TABLES_SCHEMA
    assert "term_offering_state" in TABLES_SCHEMA


def test_offerings_page_ok_for_admin(app):
    r = _login_admin(app).get("/term_offerings")
    assert r.status_code == 200


def test_semester_aliases_match_current_term(db_conn):
    ensure_term_engine_tables(db_conn)
    db_conn.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', 'خريف')"
    )
    db_conn.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', '26-27')"
    )
    db_conn.commit()
    try:
        ctx = current_term_match_context(db_conn)
        assert ctx is not None
        assert schedule_semester_matches_term_context("خريف 26-27", ctx)
        assert schedule_semester_matches_term_context("خريف 2026/2027", ctx)
        assert not schedule_semester_matches_term_context("ربيع 26-27", ctx)
        assert not schedule_semester_matches_term_context("", ctx)
        assert not schedule_semester_matches_term_context("خريف 25-26", ctx)
        assert confirm_term_label_matches("خريف 26-27", ctx)
        assert confirm_term_label_matches("خريف 2026/2027", ctx)
        assert not confirm_term_label_matches("ربيع 26-27", ctx)
    finally:
        _restore_default_term(db_conn)


def test_unpublished_offerings_hide_legacy_schedule_courses(
    app, student_auth_client, db_conn
):
    uid = uuid.uuid4().hex[:8]
    leftover = f"محطات قدرة {uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
        (leftover, f"P{uid[:6]}"),
    )
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester)
        VALUES (?, 'الأحد', '08:00-10:00', 'R1', 'أ', 'خريف 44-45')
        """,
        (leftover,),
    )
    db_conn.commit()
    set_schedule_published_at(db_conn)
    _login_admin(app).post("/term_offerings/unpublish", json={})

    r = student_auth_client.get("/students/eligible_courses?student_id=S001")
    assert r.status_code == 200
    j = r.get_json() or {}
    assert j.get("offerings_published") is False
    names = {c.get("course_name") for c in (j.get("eligible") or [])}
    assert leftover not in names


def test_published_offerings_drive_eligible_courses(app, student_auth_client, db_conn):
    uid = uuid.uuid4().hex[:8]
    offered = f"تحليل نظم {uid}"
    leftover = f"مشاريع تخرج {uid}"
    cur = db_conn.cursor()
    for name, code in ((offered, f"A{uid[:6]}"), (leftover, f"B{uid[:6]}")):
        cur.execute(
            "INSERT OR REPLACE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
            (name, code),
        )
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor, semester)
            VALUES (?, 'الأحد', '08:00-10:00', 'R1', 'أ', 'خريف 44-45')
            """,
            (name,),
        )
    db_conn.commit()
    set_schedule_published_at(db_conn)
    admin = _login_admin(app)

    save = admin.post(
        "/term_offerings/save",
        json={"course_names": [offered]},
    )
    assert save.status_code == 200, save.get_data(as_text=True)
    try:
        pub = admin.post("/term_offerings/publish", json={})
        assert pub.status_code == 200, pub.get_data(as_text=True)

        r = student_auth_client.get("/students/eligible_courses?student_id=S001")
        assert r.status_code == 200
        j = r.get_json() or {}
        assert j.get("offerings_published") is True
        names = {c.get("course_name") for c in (j.get("eligible") or [])}
        assert offered in names
        assert leftover not in names
    finally:
        admin.post("/term_offerings/unpublish", json={})


def test_schedule_rows_omits_other_semester_and_blank(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    current_name = f"FallOnly-{uid}"
    other_name = f"SpringLeft-{uid}"
    blank_name = f"BlankSem-{uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', 'خريف')"
    )
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', '98-99')"
    )
    for name, sem in (
        (current_name, "خريف 98-99"),
        (other_name, "ربيع 98-99"),
        (blank_name, ""),
    ):
        cur.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor, semester)
            VALUES (?, 'الأحد', '08:00-10:00', 'R9', 'أ', ?)
            """,
            (name, sem),
        )
    db_conn.commit()
    try:
        r = _login_admin(app).get("/schedule/rows")
        assert r.status_code == 200
        names = {x.get("course_name") for x in (r.get_json() or [])}
        assert current_name in names
        assert other_name not in names
        assert blank_name not in names
    finally:
        _restore_default_term(db_conn)


def test_clear_current_term_requires_confirm_and_spares_other_terms(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    current_name = f"ClearMe-{uid}"
    other_name = f"KeepMe-{uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', 'خريف')"
    )
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', '97-98')"
    )
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester)
        VALUES (?, 'الأحد', '08:00-10:00', 'R9', 'أ', 'خريف 97-98')
        """,
        (current_name,),
    )
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester)
        VALUES (?, 'الاثنين', '08:00-10:00', 'R9', 'أ', 'ربيع 97-98')
        """,
        (other_name,),
    )
    db_conn.commit()
    set_schedule_published_at(db_conn)
    admin = _login_admin(app)
    try:
        missing = admin.post("/schedule/clear_all", json={})
        assert missing.status_code == 400
        assert (missing.get_json() or {}).get("code") == "confirm_required"
        still = cur.execute(
            "SELECT COUNT(*) FROM schedule WHERE course_name = ?", (current_name,)
        ).fetchone()[0]
        assert int(still) == 1

        parsed = parse_ops_term("خريف", "97-98")
        label = (parsed or {}).get("ops_label") or "خريف 97-98"
        ok = admin.post("/schedule/clear_all", json={"confirm_label": label})
        assert ok.status_code == 200, ok.get_data(as_text=True)
        assert int((ok.get_json() or {}).get("deleted_rows") or 0) >= 1
        gone = cur.execute(
            "SELECT COUNT(*) FROM schedule WHERE course_name = ?", (current_name,)
        ).fetchone()[0]
        kept = cur.execute(
            "SELECT COUNT(*) FROM schedule WHERE course_name = ?", (other_name,)
        ).fetchone()[0]
        seed = cur.execute(
            "SELECT COUNT(*) FROM schedule WHERE semester = 'خريف 44-45'"
        ).fetchone()[0]
        assert int(gone) == 0
        assert int(kept) == 1
        assert int(seed) >= 1
        pub = cur.execute(
            "SELECT value FROM system_settings WHERE key = 'schedule_published_at'"
        ).fetchone()
        assert not pub or not pub[0]
    finally:
        _restore_default_term(db_conn)


def test_offerings_state_returns_current_term_and_groups(app, db_conn):
    r = _login_admin(app).get("/term_offerings/state")
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json() or {}
    assert j.get("status") == "ok"
    assert (j.get("ops_label") or "").strip()
    assert "خريف" in (j.get("ops_label") or "")
    assert isinstance(j.get("courses"), list)
    assert isinstance(j.get("groups"), list)


def test_as_int_ignores_department_name_string():
    from backend.services.term_offerings import _as_int, _label_for_term_key

    assert _as_int("الهندسة الميكانيكية") == 0
    assert _as_int("3.0") == 3
    assert _label_for_term_key("fall:2020/2021") == "خريف 2020/2021"


def test_copy_previous_term_offerings(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    offered = f"تحكم آلي {uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
        (offered, f"C{uid[:6]}"),
    )
    ensure_term_engine_tables(db_conn)
    now = "2026-01-01T00:00:00"
    cur.execute(
        """
        INSERT INTO term_course_offerings
            (term_key, course_name, department_id, status, created_at, created_by, updated_at)
        VALUES (?, ?, 0, 'offered', ?, 'test', ?)
        """,
        ("fall:2020/2021", offered, now, now),
    )
    db_conn.commit()
    admin = _login_admin(app)
    st = admin.get("/term_offerings/state")
    assert st.status_code == 200, st.get_data(as_text=True)
    prev = (st.get_json() or {}).get("previous_term") or {}
    assert prev.get("term_key") == "fall:2020/2021"
    copied = admin.post("/term_offerings/copy_previous", json={})
    assert copied.status_code == 200, copied.get_data(as_text=True)
    assert int((copied.get_json() or {}).get("saved") or 0) >= 1
    again = admin.get("/term_offerings/state")
    names = {
        c.get("course_name")
        for c in ((again.get_json() or {}).get("courses") or [])
        if c.get("offered")
    }
    assert offered in names


def test_offerings_state_groups_general_and_shared(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES ('GENERAL', 'القسم العام', 'General', 1)"
    )
    gen_id = cur.execute(
        "SELECT id FROM departments WHERE UPPER(TRIM(code)) = 'GENERAL'"
    ).fetchone()[0]
    mech_code = f"MX{uid[:6]}"
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, 'ميكانيكا اختبار', 'Mech', 1)",
        (mech_code,),
    )
    mech_id = cur.execute("SELECT id FROM departments WHERE code = ?", (mech_code,)).fetchone()[0]
    gen_course = f"رياضيات عامة {uid}"
    shared_course = f"مهارات اتصال {uid}"
    mech_course = f"آلات اختبار {uid}"
    cur.execute(
        "INSERT OR REPLACE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (gen_course, f"GS{uid[:5]}", gen_id),
    )
    cur.execute(
        "INSERT OR REPLACE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 2, ?)",
        (shared_course, f"SH{uid[:5]}", gen_id),
    )
    cur.execute(
        "INSERT OR REPLACE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 4, ?)",
        (mech_course, f"ME{uid[:5]}", mech_id),
    )
    from backend.core.college_shared_catalog import ensure_college_shared_catalog_schema

    ensure_college_shared_catalog_schema(db_conn)
    cur.execute(
        """
        INSERT INTO college_shared_catalog
            (catalog_key, share_type, canonical_course_name, canonical_course_code, units, is_active)
        VALUES (?, 'unified', ?, ?, 2, 1)
        """,
        (f"sh-{uid}", shared_course, f"SH{uid[:5]}"),
    )
    db_conn.commit()
    j = _login_admin(app).get("/term_offerings/state").get_json() or {}
    assert j.get("status") == "ok"
    kinds = {g.get("kind"): g for g in (j.get("groups") or [])}
    assert "college_general" in kinds
    assert "shared" in kinds
    general_names = {c.get("course_name") for c in kinds["college_general"].get("courses") or []}
    shared_names = {c.get("course_name") for c in kinds["shared"].get("courses") or []}
    assert gen_course in general_names
    assert shared_course in shared_names
    assert shared_course not in general_names
    assert mech_course not in general_names
    assert mech_course not in shared_names


def test_hod_save_replaces_entire_department_list(db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES ('GENERAL', 'القسم العام', 'General', 1)"
    )
    gen_id = cur.execute(
        "SELECT id FROM departments WHERE UPPER(TRIM(code)) = 'GENERAL'"
    ).fetchone()[0]
    mech_code = f"MH{uid[:6]}"
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, 'ميكانيكا حفظ', 'Mech', 1)",
        (mech_code,),
    )
    mech_id = cur.execute("SELECT id FROM departments WHERE code = ?", (mech_code,)).fetchone()[0]
    gen_course = f"فيزياء عامة {uid}"
    shared_course = f"ثقافة هندسية {uid}"
    mech_course = f"ديناميكا {uid}"
    cur.execute(
        "INSERT OR REPLACE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (gen_course, f"G{uid[:5]}", gen_id),
    )
    cur.execute(
        "INSERT OR REPLACE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 2, ?)",
        (shared_course, f"S{uid[:5]}", gen_id),
    )
    cur.execute(
        "INSERT OR REPLACE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 4, ?)",
        (mech_course, f"M{uid[:5]}", mech_id),
    )
    from backend.core.college_shared_catalog import ensure_college_shared_catalog_schema
    from backend.services.term_offerings import save_offered_courses
    from backend.services.utilities import get_current_term

    ensure_college_shared_catalog_schema(db_conn)
    cur.execute(
        """
        INSERT INTO college_shared_catalog
            (catalog_key, share_type, canonical_course_name, canonical_course_code, units, is_active)
        VALUES (?, 'unified', ?, ?, 2, 1)
        """,
        (f"sv-{uid}", shared_course, f"S{uid[:5]}"),
    )
    ensure_term_engine_tables(db_conn)
    db_conn.commit()
    name, year = get_current_term(conn=db_conn)
    parsed = parse_ops_term(name, year)
    assert parsed
    term_key = parsed["term_key"]
    first = save_offered_courses(
        db_conn,
        term_key=term_key,
        course_names=[gen_course, shared_course, mech_course],
        actor="hod",
        department_id=int(mech_id),
    )
    assert int(first.get("saved") or 0) == 3
    offered = {
        r[0]
        for r in cur.execute(
            """
            SELECT course_name FROM term_course_offerings
            WHERE term_key = ? AND department_id = ? AND status = 'offered'
            """,
            (term_key, int(mech_id)),
        )
    }
    assert offered == {gen_course, shared_course, mech_course}

    second = save_offered_courses(
        db_conn,
        term_key=term_key,
        course_names=[mech_course],
        actor="hod",
        department_id=int(mech_id),
    )
    assert int(second.get("saved") or 0) == 1
    offered2 = {
        r[0]
        for r in cur.execute(
            """
            SELECT course_name FROM term_course_offerings
            WHERE term_key = ? AND department_id = ? AND status = 'offered'
            """,
            (term_key, int(mech_id)),
        )
    }
    assert offered2 == {mech_course}


def test_specialty_eligibility_unions_general_list_and_warns_gaps(db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en, is_active) VALUES ('GENERAL', 'القسم العام', 'General', 1)"
    )
    gen_id = int(
        cur.execute(
            "SELECT id FROM departments WHERE UPPER(TRIM(code)) = 'GENERAL'"
        ).fetchone()[0]
    )
    mech_code = f"ME{uid[:6]}"
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, 'ميكانيكا أهلية', 'Mech', 1)",
        (mech_code,),
    )
    mech_id = int(cur.execute("SELECT id FROM departments WHERE code = ?", (mech_code,)).fetchone()[0])
    wanted_general = f"رياضيات عامة {uid}"
    other_general = f"كيمياء عامة {uid}"
    shared_course = f"مهارات اتصال {uid}"
    mech_course = f"ثيرموديناميك {uid}"
    for name, code, owner in (
        (wanted_general, f"G1{uid[:4]}", gen_id),
        (other_general, f"G2{uid[:4]}", gen_id),
        (shared_course, f"SH{uid[:4]}", gen_id),
        (mech_course, f"ME{uid[:4]}", mech_id),
    ):
        cur.execute(
            "INSERT OR REPLACE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
            (name, code, owner),
        )
    from backend.core.college_shared_catalog import ensure_college_shared_catalog_schema
    from backend.services.term_offerings import (
        _catalog_courses,
        _general_alignment,
        _offered_map,
        _upsert_state,
        published_offered_course_names,
        save_offered_courses,
    )
    from backend.services.utilities import get_current_term

    ensure_college_shared_catalog_schema(db_conn)
    cur.execute(
        """
        INSERT INTO college_shared_catalog
            (catalog_key, share_type, canonical_course_name, canonical_course_code, units, is_active)
        VALUES (?, 'unified', ?, ?, 2, 1)
        """,
        (f"el-{uid}", shared_course, f"SH{uid[:4]}"),
    )
    ensure_term_engine_tables(db_conn)
    db_conn.commit()
    parsed = parse_ops_term(*get_current_term(conn=db_conn))
    term_key = parsed["term_key"]
    save_offered_courses(
        db_conn,
        term_key=term_key,
        course_names=[mech_course, shared_course, wanted_general],
        actor="hod-mech",
        department_id=mech_id,
    )
    save_offered_courses(
        db_conn,
        term_key=term_key,
        course_names=[other_general],
        actor="hod-gen",
        department_id=gen_id,
    )
    _upsert_state(db_conn, term_key, mech_id, status="published", actor="hod-mech", published=True)
    _upsert_state(db_conn, term_key, gen_id, status="published", actor="hod-gen", published=True)
    db_conn.commit()

    names, pub = published_offered_course_names(
        db_conn, term_key=term_key, department_id=mech_id
    )
    assert pub is True
    assert mech_course in names
    assert shared_course in names
    assert other_general in names
    assert wanted_general not in names

    courses = _catalog_courses(db_conn, department_id=mech_id)
    offered = _offered_map(db_conn, term_key, mech_id)
    for c in courses:
        rec = offered.get(c["course_name"]) or {}
        c["offered"] = rec.get("status") == "offered"
    gaps, general_published = _general_alignment(
        db_conn, term_key, courses, mech_id, gen_id
    )
    assert general_published is True
    assert wanted_general in gaps
    assert other_general not in gaps

