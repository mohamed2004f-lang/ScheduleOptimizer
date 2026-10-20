"""المقررات المتاحة للتسجيل تستبعد المنجز بأفضل درجة وليس بآخر محاولة."""


def _uid():
    import uuid

    return uuid.uuid4().hex[:8]


def test_eligible_excludes_course_when_best_grade_passes(auth_client, db_conn):
    uid = _uid()
    sid = f"eg{uid}"
    course = f"ميكانيكا اختبار {uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO students (student_id, student_name) VALUES (?, ?)",
        (sid, f"طالب {uid}"),
    )
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
        (course, f"EG{uid[:6]}"),
    )
    # محاولات: ناجح ثم رسوب لاحق في الترتيب غير المحدد
    cur.execute(
        """
        INSERT INTO grades (student_id, semester, course_name, course_code, units, grade)
        VALUES (?, 'خريف أ', ?, ?, 3, 54)
        """,
        (sid, course, f"EG{uid[:6]}"),
    )
    cur.execute(
        """
        INSERT INTO grades (student_id, semester, course_name, course_code, units, grade)
        VALUES (?, 'خريف ب', ?, ?, 3, 39)
        """,
        (sid, course, f"EG{uid[:6]}"),
    )
    db_conn.commit()

    # اعرض المقرر كعرض فصل معتمد عبر patch لنتيجة published_offered_course_names
    from backend.services import term_offerings as to_mod

    original = to_mod.published_offered_course_names

    def _fake_offered(conn, term_key="", department_id=None):
        return {course}, True

    to_mod.published_offered_course_names = _fake_offered
    try:
        resp = auth_client.get(f"/students/eligible_courses?student_id={sid}")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        eligible_names = {c.get("course_name") for c in (body.get("eligible") or [])}
        completed_names = {c.get("course_name") for c in (body.get("completed") or [])}
        assert course not in eligible_names
        assert course in completed_names
        completed_row = next(c for c in body["completed"] if c["course_name"] == course)
        assert float(completed_row["grade"]) == 54.0
    finally:
        to_mod.published_offered_course_names = original
