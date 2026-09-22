# -*- coding: utf-8 -*-
"""ربط حصة الجدول بمجموعة تدريس تلقائياً بعد الإضافة."""


def test_ensure_schedule_slot_teaching_group(app, db_conn, auth_client):
    cur = db_conn.cursor()
    course = "مقرر_ربط_مجموعة_اختبار_فريد"
    try:
        cur.execute("INSERT OR IGNORE INTO courses (course_name) VALUES (?)", (course,))
    except Exception:
        pass
    try:
        cur.execute(
            "INSERT OR IGNORE INTO instructors (id, name, type) VALUES (1, 'أستاذ تجريبي', 'internal')"
        )
    except Exception:
        pass
    cur.execute(
        """INSERT INTO schedule (course_name, day, time, room, instructor, instructor_id, semester, department_id)
           VALUES (?,?,?,?,?,?,?,?)""",
        (course, "الأحد", "08:00-09:30", "قاعة 1", "أستاذ تجريبي", 1, "خريف 44-45", 1),
    )
    db_conn.commit()
    sid = cur.execute(
        "SELECT COALESCE(id, rowid) AS sid FROM schedule WHERE course_name = ? ORDER BY rowid DESC LIMIT 1",
        (course,),
    ).fetchone()["sid"]

    from backend.services.teaching_groups import ensure_schedule_slot_teaching_group

    try:
        gid = ensure_schedule_slot_teaching_group(db_conn, int(sid))
        db_conn.commit()
        assert gid and int(gid) > 0
        row = cur.execute(
            "SELECT teaching_group_id FROM schedule WHERE COALESCE(id, rowid) = ?",
            (int(sid),),
        ).fetchone()
        assert int(row["teaching_group_id"] or 0) == int(gid)
    finally:
        try:
            cur.execute("DELETE FROM schedule WHERE course_name = ?", (course,))
            cur.execute("DELETE FROM teaching_groups WHERE course_name = ?", (course,))
            db_conn.commit()
        except Exception:
            pass
