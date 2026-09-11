"""نشر الجدول مربوط بالفصل الحالي — لا يبقى ختم فصل سابق."""
from __future__ import annotations

from backend.services.utilities import (
    SCHEDULE_PUBLISHED_KEY,
    SCHEDULE_PUBLISHED_TERM_KEY,
    clear_schedule_published_at,
    get_schedule_published_at,
    set_schedule_published_at,
)


def _set_setting(conn, key: str, value: str) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM system_settings WHERE key = ?", (key,))
    cur.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def test_legacy_publish_without_term_is_not_active_for_current(db_conn):
    """بيانات قديمة بلا schedule_published_term تُعامل كغير منشورة للفصل الحالي."""
    _set_setting(db_conn, "current_term_name", "خريف")
    _set_setting(db_conn, "current_term_year", "26-27")
    _set_setting(db_conn, SCHEDULE_PUBLISHED_KEY, "2026-06-14T11:57:25Z")
    db_conn.cursor().execute(
        "DELETE FROM system_settings WHERE key = ?", (SCHEDULE_PUBLISHED_TERM_KEY,)
    )
    db_conn.commit()

    assert get_schedule_published_at(db_conn, for_current_term=True) is None
    assert get_schedule_published_at(db_conn, for_current_term=False) == "2026-06-14T11:57:25Z"


def test_publish_binds_to_current_term_and_mismatched_is_ignored(db_conn):
    _set_setting(db_conn, "current_term_name", "خريف")
    _set_setting(db_conn, "current_term_year", "26-27")
    published = set_schedule_published_at(db_conn)
    assert published
    assert get_schedule_published_at(db_conn) == published

    # ختم فصل آخر (أو stale) لا يُحسب للفصل الحالي
    _set_setting(db_conn, SCHEDULE_PUBLISHED_TERM_KEY, "spring:2025/2026")
    assert get_schedule_published_at(db_conn, for_current_term=True) is None


def test_find_schedule_row_matches_canonical_day_time(db_conn):
    import uuid

    from backend.services.schedule import _find_schedule_row_for_write

    cur = db_conn.cursor()
    name = f"FindSlot-{uuid.uuid4().hex[:8]}"
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, semester)
        VALUES (?, 'السبت', '11:00-13:00', 'A1', 'أ', 'خريف 44-45')
        """,
        (name,),
    )
    db_conn.commit()
    row, sid = _find_schedule_row_for_write(
        db_conn,
        {"course_name": name, "day": "السبت", "time": "11:00-13:00"},
        0,
    )
    assert row is not None
    assert sid > 0


def test_clear_removes_publish_and_term(db_conn):
    _set_setting(db_conn, "current_term_name", "خريف")
    _set_setting(db_conn, "current_term_year", "26-27")
    set_schedule_published_at(db_conn)
    clear_schedule_published_at(db_conn)
    assert get_schedule_published_at(db_conn, for_current_term=False) is None
    cur = db_conn.cursor()
    cur.execute(
        "SELECT value FROM system_settings WHERE key = ?", (SCHEDULE_PUBLISHED_TERM_KEY,)
    )
    assert cur.fetchone() is None
