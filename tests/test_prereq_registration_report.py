"""تقرير مراجعة التسجيل (أسبقية + وحدات)."""
from backend.services.prereg_helpers import build_prereq_registration_issues_report


def _uid():
    import uuid

    return uuid.uuid4().hex[:8]


def test_prereq_report_coregister_and_failed(db_conn):
    uid = _uid()
    sid = f"pr{uid}"
    dep = f"تابع أسبقية {uid}"
    pre = f"متطلب أسبقية {uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO students (student_id, student_name) VALUES (?, ?)",
        (sid, f"طالب أسبقية {uid}"),
    )
    code_dep = f"D{uid[:6]}"
    code_pre = f"P{uid[:6]}"
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
        (dep, code_dep),
    )
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
        (pre, code_pre),
    )
    cur.execute(
        "INSERT OR IGNORE INTO prereqs (course_name, required_course_name) VALUES (?, ?)",
        (dep, pre),
    )
    # زوج متطلب+تابع معاً في التسجيل
    cur.execute(
        "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
        (sid, dep),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
        (sid, pre),
    )
    db_conn.commit()

    data = build_prereq_registration_issues_report(db_conn, {sid})
    kinds = {it["kind"] for it in data["items"] if it["student_id"] == sid}
    assert "coregister_new" in kinds or "in_progress" in kinds

    # رسوب سابق للمتطلب دون إعادته: طالب آخر
    sid2 = f"pf{uid}"
    cur.execute(
        "INSERT OR REPLACE INTO students (student_id, student_name) VALUES (?, ?)",
        (sid2, f"طالب رسوب {uid}"),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
        (sid2, dep),
    )
    cur.execute(
        """
        INSERT INTO grades (student_id, semester, course_name, course_code, units, grade)
        VALUES (?, 'ف1', ?, ?, 3, 40)
        """,
        (sid2, pre, code_pre),
    )
    db_conn.commit()

    data2 = build_prereq_registration_issues_report(db_conn, {sid2})
    match = [it for it in data2["items"] if it["student_id"] == sid2]
    assert match, data2
    failed = [it for it in match if it["kind"] == "failed_not_retaking"]
    assert failed, match
    assert float(failed[0]["prereq_grade"]) == 40.0
    assert failed[0]["dependent_course"] == dep
    assert failed[0]["prereq_course"] == pre


def test_prereq_registration_report_api(auth_client, db_conn):
    uid = _uid()
    sid = f"pa{uid}"
    dep = f"API تابع {uid}"
    pre = f"API متطلب {uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO students (student_id, student_name) VALUES (?, ?)",
        (sid, f"طالب API {uid}"),
    )
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
        (dep, f"AD{uid[:6]}"),
    )
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
        (pre, f"AP{uid[:6]}"),
    )
    cur.execute(
        "INSERT OR IGNORE INTO prereqs (course_name, required_course_name) VALUES (?, ?)",
        (dep, pre),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
        (sid, dep),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
        (sid, pre),
    )
    db_conn.commit()

    page = auth_client.get("/registration_review_report_page")
    assert page.status_code == 200
    legacy = auth_client.get("/prereq_registration_report_page")
    assert legacy.status_code == 200

    resp = auth_client.get("/students/registration_review_report")
    assert resp.status_code == 200
    body = resp.get_json() or {}
    assert body.get("status") == "ok"
    assert "items" in body
    assert "summary" in body
    assert body["summary"].get("load_min") == 12
    assert body["summary"].get("load_max") == 18

    match = [it for it in (body.get("items") or []) if it.get("student_id") == sid]
    assert match, body.get("summary")

    caps = auth_client.get("/auth/check").get_json() or {}
    assert (caps.get("capabilities") or {}).get("nav_prereq_registration_report") is True


def test_registration_review_load_under_and_over(db_conn):
    uid = _uid()
    sid_lo = f"lo{uid}"
    sid_hi = f"hi{uid}"
    cur = db_conn.cursor()
    for sid, name in ((sid_lo, f"منخفض {uid}"), (sid_hi, f"مرتفع {uid}")):
        cur.execute(
            "INSERT OR REPLACE INTO students (student_id, student_name) VALUES (?, ?)",
            (sid, name),
        )
    # مقرر 3 وحدات × 3 = 9 (<12)
    for i in range(3):
        cn = f"حمل منخفض {uid}-{i}"
        cur.execute(
            "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
            (cn, f"L{uid[:4]}{i}"),
        )
        cur.execute(
            "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
            (sid_lo, cn),
        )
    # مقرر 3 وحدات × 7 = 21 (>18)
    for i in range(7):
        cn = f"حمل مرتفع {uid}-{i}"
        cur.execute(
            "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
            (cn, f"H{uid[:4]}{i}"),
        )
        cur.execute(
            "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
            (sid_hi, cn),
        )
    db_conn.commit()

    data = build_prereq_registration_issues_report(
        db_conn, {sid_lo, sid_hi}, group="load"
    )
    kinds = {(it["student_id"], it["kind"]) for it in data["items"]}
    assert (sid_lo, "load_under_12") in kinds
    assert (sid_hi, "load_over_18") in kinds
    lo = next(it for it in data["items"] if it["student_id"] == sid_lo)
    assert float(lo["total_units"]) == 9.0
    hi = next(it for it in data["items"] if it["student_id"] == sid_hi)
    assert float(hi["total_units"]) == 21.0
