"""استعلامات جدول المستخدمين."""
from __future__ import annotations

from typing import Any


def _user_row_to_dict(r) -> dict[str, Any]:
    """يحوّل صف SELECT إلى قاموس مستخدم (مع department_id عند توفر العمود)."""
    dept_raw = r[6] if len(r) > 6 else None
    dept_out = None
    if dept_raw not in (None, ""):
        try:
            dept_out = int(dept_raw)
        except (TypeError, ValueError):
            dept_out = None
    return {
        "username": r[0],
        "role": r[1],
        "student_id": r[2],
        "instructor_id": r[3],
        "is_supervisor": int(r[4] or 0),
        "is_active": int(r[5] or 1),
        "department_id": dept_out,
    }


def fetch_all_users_ordered(
    conn,
    *,
    scope_mode: str = "none",
    scope_department_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    قائمة المستخدمين مرتبة باسم المستخدم (بدون كلمات مرور).

    scope_mode:
      - "none": كل المستخدمين.
      - "department": تصفية حسب القسم (مع طلاب عبر البرامج).
      - "empty": قائمة فارغة.
    """
    if scope_mode == "empty":
        return []
    cur = conn.cursor()
    if scope_mode != "department" or scope_department_id is None:
        rows = cur.execute(
            "SELECT username, role, student_id, instructor_id, "
            "COALESCE(is_supervisor,0) AS is_supervisor, "
            "COALESCE(is_active,1) AS is_active, "
            "department_id "
            "FROM users ORDER BY username"
        ).fetchall()
    else:
        dep = int(scope_department_id)
        rows = cur.execute(
            """
            SELECT DISTINCT u.username, u.role, u.student_id, u.instructor_id,
                   COALESCE(u.is_supervisor,0) AS is_supervisor,
                   COALESCE(u.is_active,1) AS is_active,
                   u.department_id
            FROM users u
            LEFT JOIN students s ON s.student_id = u.student_id
            LEFT JOIN instructors ins ON ins.id = u.instructor_id
            WHERE (
              COALESCE(u.department_id, s.department_id, ins.department_id) = ?
              OR EXISTS (
                SELECT 1 FROM programs p
                WHERE p.department_id = ?
                  AND s.student_id IS NOT NULL
                  AND (
                    (s.current_program_id IS NOT NULL AND p.id = s.current_program_id)
                    OR (s.admission_program_id IS NOT NULL AND p.id = s.admission_program_id)
                  )
              )
            )
            ORDER BY u.username
            """,
            (dep, dep),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(_user_row_to_dict(r))
    return out


def fetch_user_row_by_username_ci(conn, username: str):
    """صف مستخدم واحد مطابقة لاسم المستخدم دون حساسية لحالة الأحرف."""
    cur = conn.cursor()
    return cur.execute(
        "SELECT username, role, student_id, instructor_id, COALESCE(is_supervisor,0), COALESCE(is_active,1), department_id "
        "FROM users WHERE lower(username) = lower(?)",
        (username,),
    ).fetchone()


def fetch_user_row_after_write_ci(conn, username: str):
    """بعد INSERT/UPDATE — نفس حقول قائمة المستخدمين."""
    cur = conn.cursor()
    return cur.execute(
        "SELECT username, role, student_id, instructor_id, "
        "COALESCE(is_supervisor,0) AS is_supervisor, COALESCE(is_active,1) AS is_active, department_id "
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
