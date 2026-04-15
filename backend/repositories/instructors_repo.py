"""استعلامات جدول أعضاء هيئة التدريس."""
from __future__ import annotations


def exists_instructor_id(conn, instructor_id: int | None) -> bool:
    if instructor_id is None:
        return False
    cur = conn.cursor()
    row = cur.execute(
        "SELECT 1 FROM instructors WHERE id = ? LIMIT 1",
        (instructor_id,),
    ).fetchone()
    return row is not None
