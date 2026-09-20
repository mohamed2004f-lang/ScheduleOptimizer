# -*- coding: utf-8 -*-
"""تعارضات الطلبة تُحسب حياً من schedule حتى لو conflict_report فارغ."""


def test_timetable_conflicts_live_without_conflict_report(app, db_conn, auth_client):
    cur = db_conn.cursor()
    try:
        cur.execute("DELETE FROM conflict_report")
    except Exception:
        pass
    try:
        cur.execute("DELETE FROM optimized_schedule")
    except Exception:
        pass

    # مقررات لازمة لـ FK إن وُجد
    for name in ("مقرر أ", "مقرر ب"):
        try:
            cur.execute(
                "INSERT OR IGNORE INTO courses (course_name) VALUES (?)",
                (name,),
            )
        except Exception:
            pass

    cur.execute("DELETE FROM schedule")
    cur.execute("DELETE FROM registrations WHERE student_id = ?", ("S9001",))
    cur.execute(
        "INSERT OR IGNORE INTO students (student_id, student_name) VALUES (?, ?)",
        ("S9001", "طالب تعارض"),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
        ("S9001", "مقرر أ"),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
        ("S9001", "مقرر ب"),
    )
    cur.execute(
        """INSERT INTO schedule (course_name, day, time, room, instructor, semester)
           VALUES (?,?,?,?,?,?)""",
        ("مقرر أ", "السبت", "09:00-11:00", "-", "أ", "Fall 2024/2025"),
    )
    cur.execute(
        """INSERT INTO schedule (course_name, day, time, room, instructor, semester)
           VALUES (?,?,?,?,?,?)""",
        ("مقرر ب", "السبت", "09:00-11:00", "-", "ب", "Fall 2024/2025"),
    )
    db_conn.commit()

    r = auth_client.get("/students/timetable/conflicts?live=1")
    assert r.status_code == 200, r.data
    data = r.get_json()
    assert data is not None
    conflicts = data.get("conflicts") or []
    assert len(conflicts) >= 1, data
    assert data.get("source") == "live_schedule"
    n = cur.execute("SELECT COUNT(*) AS c FROM conflict_report").fetchone()["c"]
    assert int(n) == 0
