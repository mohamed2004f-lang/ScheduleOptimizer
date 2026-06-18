"""Quick PG check for announcements and notifications."""
from backend.services.utilities import get_connection

with get_connection() as conn:
    cur = conn.cursor()
    for t in ("notifications", "faculty_course_announcements"):
        try:
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"{t}: OK, rows={n}")
        except Exception as e:
            print(f"{t}: FAIL — {e}")

    try:
        cur.execute(
            'INSERT INTO notifications ("user", title, body, is_read, created_at) VALUES (?, ?, ?, ?, ?)',
            ("_test_user", "t", "b", 0, "2026-01-01"),
        )
        conn.rollback()
        print("notifications INSERT with quoted user: OK")
    except Exception as e:
        print(f"notifications INSERT quoted: FAIL — {e}")

    try:
        cur.execute(
            "INSERT INTO notifications (user, title, body, is_read, created_at) VALUES (?, ?, ?, ?, ?)",
            ("_test_user", "t", "b", 0, "2026-01-01"),
        )
        conn.rollback()
        print("notifications INSERT unquoted user: OK")
    except Exception as e:
        print(f"notifications INSERT unquoted: FAIL — {e}")

    try:
        cols = cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='faculty_course_plans' ORDER BY ordinal_position"
        ).fetchall()
        print("faculty_course_plans cols:", [x[0] for x in cols])
        rows = cur.execute(
            "SELECT week_no, week_topic, lecture_status, resources_text, linked_clo FROM faculty_course_plans WHERE section_id=? AND instructor_id=?",
            (21, 2),
        ).fetchall()
        print("plan rows:", rows)
    except Exception as e:
        print(f"plan query: FAIL — {e}")
