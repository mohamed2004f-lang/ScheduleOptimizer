"""إصلاح schedule.id بلا تسلسل على PostgreSQL."""
from __future__ import annotations


def test_ensure_schedule_id_identity_sqlite_fills_null(db_conn):
    from backend.database.backfills import ensure_schedule_id_identity

    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester, id)
        VALUES ('IdFixCourse', 'السبت', '08:00-09:00', 'R1', 'أ', 'خريف 44-45', NULL)
        """
    )
    db_conn.commit()
    before = cur.execute(
        "SELECT id FROM schedule WHERE course_name = 'IdFixCourse'"
    ).fetchone()[0]
    assert before is None
    out = ensure_schedule_id_identity(db_conn)
    assert out.get("ok") is True
    after = cur.execute(
        "SELECT id FROM schedule WHERE course_name = 'IdFixCourse'"
    ).fetchone()[0]
    assert after is not None
    assert int(after) > 0
