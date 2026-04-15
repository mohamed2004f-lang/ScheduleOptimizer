"""استعلامات جدول المستخدمين."""
from __future__ import annotations

from typing import Any


def fetch_all_users_ordered(conn) -> list[dict[str, Any]]:
    """قائمة المستخدمين مرتبة باسم المستخدم (بدون كلمات مرور)."""
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT username, role, student_id, instructor_id, "
        "COALESCE(is_supervisor,0) AS is_supervisor, "
        "COALESCE(is_active,1) AS is_active "
        "FROM users ORDER BY username"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "username": r[0],
                "role": r[1],
                "student_id": r[2],
                "instructor_id": r[3],
                "is_supervisor": int(r[4] or 0),
                "is_active": int(r[5] or 1),
            }
        )
    return out


def fetch_user_row_by_username_ci(conn, username: str):
    """صف مستخدم واحد مطابقة لاسم المستخدم دون حساسية لحالة الأحرف."""
    cur = conn.cursor()
    return cur.execute(
        "SELECT username, role, student_id, instructor_id, COALESCE(is_supervisor,0), COALESCE(is_active,1) "
        "FROM users WHERE lower(username) = lower(?)",
        (username,),
    ).fetchone()


def fetch_user_row_after_write_ci(conn, username: str):
    """بعد INSERT/UPDATE — نفس حقول قائمة المستخدمين."""
    cur = conn.cursor()
    return cur.execute(
        "SELECT username, role, student_id, instructor_id, "
        "COALESCE(is_supervisor,0) AS is_supervisor, COALESCE(is_active,1) AS is_active "
        "FROM users WHERE lower(username) = lower(?)",
        (username,),
    ).fetchone()


def fetch_username_row_ci(conn, username: str):
    """صف واحد (username,) لتشخيص تعارض حالة الأحرف."""
    cur = conn.cursor()
    return cur.execute(
        "SELECT username FROM users WHERE lower(username) = lower(?) LIMIT 1",
        (username,),
    ).fetchone()
