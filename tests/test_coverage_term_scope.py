"""تغطية الفصل الحالي فقط — بلا رجوع لبقايا فصول أخرى بعد التفريغ."""

import uuid

from backend.services.coverage_insights import (
    schedule_distinct_course_names_for_coverage,
    schedule_other_term_leftover_summary,
)


def _set_term(cur, name: str, year: str) -> None:
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', ?)",
        (name,),
    )
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', ?)",
        (year,),
    )


def test_coverage_ignores_other_term_schedule_rows(db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    _set_term(cur, "خريف", "88-89")
    other_course = f"OtherTermCourse{uid}"
    current_course = f"CurrentTermCourse{uid}"
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester)
        VALUES (?, 'السبت', '09:00-11:00', 'A1', 'أ', 'ربيع 70-71')
        """,
        (other_course,),
    )
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester)
        VALUES (?, 'الأحد', '09:00-11:00', 'A2', 'ب', 'خريف 88-89')
        """,
        (current_course,),
    )
    db_conn.commit()

    names, scope = schedule_distinct_course_names_for_coverage(
        db_conn, cur, "خريف 88-89"
    )
    assert scope == "current_term"
    assert current_course in names
    assert other_course not in names

    leftover = schedule_other_term_leftover_summary(db_conn, cur)
    assert leftover["row_count"] >= 1
    assert leftover["distinct_courses"] >= 1
    assert leftover["warning_ar"]


def test_coverage_empty_current_term_no_all_schedule_fallback(db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    _set_term(cur, "خريف", "91-92")
    leftover_course = f"LeftoverOnly{uid}"
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester)
        VALUES (?, 'الإثنين', '10:00-12:00', 'B1', 'ج', 'ربيع 60-61')
        """,
        (leftover_course,),
    )
    db_conn.commit()

    names, scope = schedule_distinct_course_names_for_coverage(
        db_conn, cur, "خريف 91-92"
    )
    assert names == []
    assert scope == "current_term_empty"
    assert leftover_course not in names

    leftover = schedule_other_term_leftover_summary(db_conn, cur)
    assert leftover["row_count"] >= 1
    assert "فصول أخرى" in (leftover["warning_ar"] or "")


def test_registration_coverage_api_reports_leftover_not_schedule_count(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    _set_term(cur, "خريف", "92-93")
    leftover_course = f"ApiLeftover{uid}"
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester)
        VALUES (?, 'الثلاثاء', '11:00-13:00', 'C1', 'د', 'ربيع 55-56')
        """,
        (leftover_course,),
    )
    db_conn.commit()

    headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    with app.test_client() as c:
        assert (
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            ).status_code
            == 200
        )
        r = c.get("/schedule/registration_coverage", headers=headers)
        assert r.status_code == 200
        cov = r.get_json() or {}
        assert cov.get("schedule_scope") == "current_term_empty"
        assert int((cov.get("counts") or {}).get("schedule_distinct") or 0) == 0
        assert int((cov.get("counts") or {}).get("other_term_schedule_rows") or 0) >= 1
        assert "فصول أخرى" in (cov.get("leftover_warning_ar") or "")
        assert leftover_course not in (cov.get("extra_in_schedule") or [])


def test_exam_coverage_api_same_term_scope(app, db_conn):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    _set_term(cur, "خريف", "93-94")
    leftover_course = f"ExamLeftover{uid}"
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type TEXT NOT NULL,
            exam_id INTEGER,
            course_name TEXT NOT NULL,
            exam_date TEXT,
            exam_time TEXT,
            room TEXT,
            instructor TEXT
        )
        """
    )
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester)
        VALUES (?, 'الأربعاء', '09:00-11:00', 'D1', 'هـ', 'ربيع 40-41')
        """,
        (leftover_course,),
    )
    cur.execute(
        """
        INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor)
        VALUES ('midterm', NULL, ?, '2026-01-10', '09:00-11:00', 'E1', '')
        """,
        (leftover_course,),
    )
    db_conn.commit()

    headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    with app.test_client() as c:
        assert (
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            ).status_code
            == 200
        )
        r = c.get("/exams/midterm/schedule_coverage", headers=headers)
        assert r.status_code == 200
        cov = r.get_json() or {}
        assert cov.get("coverage_available") is True
        assert cov.get("schedule_scope") in ("current_term_empty", "none")
        assert int((cov.get("counts") or {}).get("schedule_distinct") or 0) == 0
        assert leftover_course not in (cov.get("missing_from_exams") or [])
        assert leftover_course in (cov.get("extras_in_exams_not_in_schedule") or [])
        warn = cov.get("leftover_warning_ar") or ""
        assert "فصول أخرى" in warn or "فارغ" in warn


def test_schedule_clear_other_terms_spares_current(app, db_conn):
    """mode=other يحذف بقايا الفصل السابق ويُبقي صفوف الفصل الحالي."""
    from backend.services.term_engine import ensure_term_engine_tables

    ensure_term_engine_tables(db_conn)
    cur = db_conn.cursor()
    db_conn.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', 'خريف')"
    )
    db_conn.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', '26-27')"
    )
    uid = uuid.uuid4().hex[:8]
    spring = f"SpringLeft{uid}"
    fall = f"FallKeep{uid}"
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester)
        VALUES (?, 'السبت', '09:00-11:00', 'A1', 'أ', 'ربيع 25-26')
        """,
        (spring,),
    )
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester)
        VALUES (?, 'الأحد', '09:00-11:00', 'A2', 'ب', 'خريف 26-27')
        """,
        (fall,),
    )
    db_conn.commit()

    c = app.test_client()
    try:
        assert (
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            ).status_code
            == 200
        )
        r = c.post(
            "/schedule/clear_all",
            json={"confirm_label": "خريف 26-27", "mode": "other"},
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json() or {}
        assert body.get("status") == "ok"
        assert body.get("mode") == "other"
        assert int(body.get("deleted_rows") or 0) >= 1

        left_spring = cur.execute(
            "SELECT COUNT(*) FROM schedule WHERE course_name = ?", (spring,)
        ).fetchone()[0]
        left_fall = cur.execute(
            "SELECT COUNT(*) FROM schedule WHERE course_name = ?", (fall,)
        ).fetchone()[0]
        assert int(left_spring) == 0
        assert int(left_fall) == 1
    finally:
        db_conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', 'خريف')"
        )
        db_conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', '44-45')"
        )
        # استعادة صفوف البذرة إن حُذفت مع بقايا الفصول الأخرى
        left_seed = cur.execute(
            "SELECT COUNT(*) FROM schedule WHERE semester = 'خريف 44-45'"
        ).fetchone()[0]
        if int(left_seed or 0) < 1:
            cur.execute(
                """
                INSERT INTO schedule (course_name, day, time, room, instructor, semester)
                VALUES ('رياضيات 1', 'الأحد', '08:00-09:30', 'قاعة 1', 'أستاذ  تجريبي', 'خريف 44-45')
                """
            )
            cur.execute(
                """
                INSERT INTO schedule (course_name, day, time, room, instructor_id, semester)
                VALUES ('فيزياء 1', 'الاثنين', '10:00-11:30', 'قاعة 2', 1, 'خريف 44-45')
                """
            )
        db_conn.commit()
