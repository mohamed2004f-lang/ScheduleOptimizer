"""استعلامات جدول الطلاب."""
from __future__ import annotations


def exists_student_id(conn, student_id: str) -> bool:
    if not (student_id or "").strip():
        return False
    cur = conn.cursor()
    row = cur.execute(
        "SELECT 1 FROM students WHERE student_id = ? LIMIT 1",
        ((student_id or "").strip(),),
    ).fetchone()
    return row is not None
