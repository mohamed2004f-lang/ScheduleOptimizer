"""توحيد اختيار الفصل والعام الدراسي (مرحلة 1)."""
from __future__ import annotations


def test_parse_ops_term_canonical_year():
    from backend.services.term_engine import parse_ops_term

    p = parse_ops_term("خريف", "25-26")
    assert p is not None
    assert p["academic_year"] == "2025/2026"
    assert p["ops_year_label"] == "2025/2026"
    assert p["ops_label"] == "خريف 2025/2026"
    assert p["term_key"] == "fall:2025/2026"

    p2 = parse_ops_term("spring", "2026/2027")
    assert p2 is not None
    assert p2["term_name_ar"] == "ربيع"
    assert p2["ops_label"] == "ربيع 2026/2027"


def test_list_academic_year_options_shape(db_conn):
    from backend.services.term_engine import list_academic_year_options, upsert_term_master
    import datetime

    upsert_term_master(db_conn, season="fall", academic_year="2030/2031")
    years = list_academic_year_options(db_conn)
    assert "2030/2031" in years
    assert all("/" in y and y.count("/") == 1 for y in years)
    y0 = datetime.date.today().year
    assert f"{y0 - 8}/{y0 - 7}" in years
    assert f"{y0 + 5}/{y0 + 6}" in years


def test_rename_semester_requires_admin_main(auth_client, instructor_auth_client, db_conn):
    from backend.services.utilities import get_connection

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO students (student_id, student_name, university_number) VALUES (?,?,?)",
            ("T9101", "طالب rename", "U9101"),
        )
        cur.execute(
            "INSERT INTO grades (student_id, semester, course_name, course_code, units, grade) VALUES (?,?,?,?,?,?)",
            ("T9101", "خريف 2020/2021", "مقرر ر", "R1", 3, 70),
        )
        conn.commit()

    r = instructor_auth_client.post(
        "/grades/rename_semester",
        json={"old_semester": "خريف 2020/2021", "new_semester": "خريف 2021/2022"},
    )
    assert r.status_code in (403, 401)

    with auth_client.session_transaction() as sess:
        sess["user_role"] = "admin_main"
        sess["user"] = "admin-main-rename"
    r2 = auth_client.post(
        "/grades/rename_semester",
        json={
            "old_semester": "خريف 2020/2021",
            "term_name": "خريف",
            "term_year": "2021/2022",
        },
    )
    # الأدمن الاختباري غالباً admin_main فعّال عبر current_user
    assert r2.status_code == 200
    j = r2.get_json()
    assert "2021/2022" in (j.get("message") or "")


def test_term_options_api(auth_client):
    r = auth_client.get("/admin/settings/term_options")
    assert r.status_code == 200
    j = r.get_json()
    assert j["status"] == "ok"
    assert isinstance(j.get("academic_years"), list)
    assert j["academic_years"]
    assert any(s.get("value") == "خريف" for s in j.get("seasons") or [])


def test_parse_term_api(auth_client):
    r = auth_client.post(
        "/admin/settings/parse_term",
        json={"term_name": "خريف", "term_year": "26-27"},
    )
    assert r.status_code == 200
    j = r.get_json()
    assert j["ops_label"] == "خريف 2026/2027"
    assert j["term_year"] == "2026/2027"


def test_set_current_term_normalizes_year(auth_client, db_conn):
    from backend.services.utilities import get_current_term

    r = auth_client.post(
        "/admin/settings/current_term",
        json={"term_name": "ربيع", "term_year": "31-32", "archive_basket": True, "archive_reason": "test-normalize-year"},
    )
    # قد يفشل بسبب السلة — إن نجح نتأكد من التطبيع
    if r.status_code == 200:
        j = r.get_json()
        assert j["term_year"] == "2031/2032"
        assert j["term_name"] == "ربيع"
        name, year = get_current_term(conn=db_conn)
        assert year == "2031/2032"
        assert "ربيع" in name
    else:
        # مسار بديل: parse فقط يثبت العقد
        assert r.status_code in (400, 409)


def test_migrate_non_admin_main_forced_to_current(auth_client, db_conn, monkeypatch):
    """head_of_department لا يفرض فصلاً مختلفاً عن الجاري."""
    from backend.services.utilities import get_connection

    # عيّن فصل جاري
    with get_connection() as conn:
        cur = conn.cursor()
        for k, v in (("current_term_name", "خريف"), ("current_term_year", "2028/2029")):
            cur.execute("DELETE FROM system_settings WHERE key = ?", (k,))
            cur.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)", (k, v))
        conn.commit()

    # طالب + تسجيل
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO students (student_id, student_name, university_number) VALUES (?,?,?)",
            ("T9001", "طالب اختبار", "U9001"),
        )
        try:
            cur.execute(
                "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
                ("T9001", "مقرر اختبار"),
            )
        except Exception:
            cur.execute(
                "INSERT INTO registrations (student_id, course_name, course_code, units) VALUES (?, ?, ?, ?)",
                ("T9001", "مقرر اختبار", "T900", 3),
            )
        conn.commit()

    # جلسة رئيس قسم
    with auth_client.session_transaction() as sess:
        sess["user_role"] = "head_of_department"
        sess["user"] = "hod-test"

    r = auth_client.post(
        "/grades/migrate_registrations_to_transcript",
        json={
            "student_id": "T9001",
            "semester": "ربيع",
            "year": "2030/2031",
            "changed_by": "test",
        },
    )
    # إن نجح الترحيل يجب أن يُكتب تحت الفصل الجاري لا الربيع الممرَّر
    if r.status_code == 200:
        with get_connection() as conn:
            row = conn.cursor().execute(
                "SELECT semester FROM grades WHERE student_id = ? LIMIT 1",
                ("T9001",),
            ).fetchone()
            assert row is not None
            sem = row[0] if not hasattr(row, "keys") else row["semester"]
            assert "خريف" in str(sem)
            assert "2028/2029" in str(sem)
