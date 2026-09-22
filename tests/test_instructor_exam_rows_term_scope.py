"""عرض امتحانات الأستاذ: مقررات تكليفه في الفصل الحالي فقط (لا بقايا فصول سابقة)."""

import uuid


def _set_term(cur, name: str, year: str) -> None:
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', ?)",
        (name,),
    )
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', ?)",
        (year,),
    )


def _ensure_exams_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type TEXT NOT NULL,
            exam_id INTEGER,
            course_name TEXT,
            exam_date TEXT,
            exam_time TEXT,
            room TEXT DEFAULT '',
            instructor TEXT DEFAULT '',
            teaching_group_id INTEGER
        )
        """
    )


def test_instructor_exam_rows_exclude_other_term_courses(
    app, db_conn, instructor_auth_client
):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    _ensure_exams_table(cur)
    term_name, term_year = "خريف", f"9{uid[:2]}-9{uid[2:4]}"
    sem = f"{term_name} {term_year}"
    _set_term(cur, term_name, term_year)

    mine = f"MineCourse{uid}"
    leftover = f"LeftoverChem{uid}"
    other_inst = f"OtherInstCourse{uid}"

    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
        (mine, f"M{uid[:6]}"),
    )
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
        (leftover, f"L{uid[:6]}"),
    )
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
        (other_inst, f"O{uid[:6]}"),
    )

    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, instructor_id, semester)
        VALUES (?, 'السبت', '09:00-11:00', 'R1', 'أستاذ تجريبي', 1, ?)
        """,
        (mine, sem),
    )
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, instructor_id, semester)
        VALUES (?, 'الأحد', '09:00-11:00', 'R2', 'آخر', 999, ?)
        """,
        (other_inst, sem),
    )
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, instructor_id, semester)
        VALUES (?, 'الإثنين', '09:00-11:00', 'R3', 'أستاذ تجريبي', 1, 'ربيع 10-11')
        """,
        (leftover,),
    )

    cur.execute(
        """
        INSERT INTO exams (exam_type, course_name, exam_date, exam_time, room, instructor)
        VALUES ('midterm', ?, '2026-05-09', '09:00-12:00', 'E1', 'أستاذ تجريبي')
        """,
        (mine,),
    )
    cur.execute(
        """
        INSERT INTO exams (exam_type, course_name, exam_date, exam_time, room, instructor)
        VALUES ('midterm', ?, '2026-05-10', '09:00-12:00', 'E2', 'أستاذ تجريبي')
        """,
        (leftover,),
    )
    cur.execute(
        """
        INSERT INTO exams (exam_type, course_name, exam_date, exam_time, room, instructor)
        VALUES ('midterm', ?, '2026-05-11', '09:00-12:00', 'E3', 'آخر')
        """,
        (other_inst,),
    )
    db_conn.commit()

    rows = instructor_auth_client.get("/exams/midterm/rows").get_json() or []
    names = {(r.get("course_name") or "").strip() for r in rows}
    assert mine in names
    assert leftover not in names
    assert other_inst not in names
