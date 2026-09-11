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


def test_collapse_term_ws_coerces_non_string():
    """حماية من صفوف PG عند فهرسة خاطئة (int بدل نص الفصل)."""
    from backend.services.term_engine import (
        _collapse_term_ws,
        schedule_semester_matches_term_context,
    )

    assert _collapse_term_ws(2) == "2"
    assert schedule_semester_matches_term_context(2, {"labels": set(), "seasons": [], "years": []}) is False


def test_pg_row_adapter_duplicate_coalesce_loses_semester():
    """بدون AS semester يتصادم اسم COALESCE في dict_row ويُفقد الفصل."""
    from backend.database.pg_compat import _PgRowAdapter

    # يحاكي ما يفعله السائق عندما يتكرر اسم العمود coalesce
    row = _PgRowAdapter(
        {"id": 19, "coalesce": 2},
        ("id", "coalesce", "coalesce"),
    )
    assert row[0] == 19
    assert row[1] == 2  # department_id وليس semester — سبب تعطّل التفريغ السابق
    assert list(row.keys()) == ["id", "coalesce"]
