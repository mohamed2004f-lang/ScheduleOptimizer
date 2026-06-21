"""استعلامات جدول المستخدمين."""
from __future__ import annotations

from typing import Any

USER_LIST_SELECT = (
    "SELECT username, role, student_id, instructor_id, "
    "COALESCE(is_supervisor,0) AS is_supervisor, "
    "COALESCE(is_active,1) AS is_active, "
    "department_id, "
    "COALESCE(is_system_account,0) AS is_system_account, "
    "role_profile_id, display_title_ar, "
    "COALESCE(is_dept_quality_coordinator,0) AS is_dept_quality_coordinator "
    "FROM users"
)

USER_LIST_SELECT_LEGACY = (
    "SELECT username, role, student_id, instructor_id, "
    "COALESCE(is_supervisor,0) AS is_supervisor, "
    "COALESCE(is_active,1) AS is_active, "
    "department_id "
    "FROM users"
)


def _user_row_to_dict(r) -> dict[str, Any]:
    """يحوّل صف SELECT إلى قاموس مستخدم."""
    if hasattr(r, "keys"):
        d = dict(r)
        return {
            "username": d.get("username"),
            "role": d.get("role"),
            "student_id": d.get("student_id"),
            "instructor_id": d.get("instructor_id"),
            "is_supervisor": int(d.get("is_supervisor") or 0),
            "is_active": int(d.get("is_active") or 1),
            "department_id": _int_or_none(d.get("department_id")),
            "is_system_account": int(d.get("is_system_account") or 0),
            "role_profile_id": _int_or_none(d.get("role_profile_id")),
            "display_title_ar": d.get("display_title_ar"),
            "is_dept_quality_coordinator": int(d.get("is_dept_quality_coordinator") or 0),
        }
    dept_out = _int_or_none(r[6] if len(r) > 6 else None)
    out = {
        "username": r[0],
        "role": r[1],
        "student_id": r[2],
        "instructor_id": r[3],
        "is_supervisor": int(r[4] or 0),
        "is_active": int(r[5] or 1),
        "department_id": dept_out,
        "is_system_account": 0,
        "role_profile_id": None,
        "display_title_ar": None,
        "is_dept_quality_coordinator": 0,
    }
    if len(r) > 7:
        out["is_system_account"] = int(r[7] or 0)
    if len(r) > 8:
        out["role_profile_id"] = _int_or_none(r[8])
    if len(r) > 9:
        out["display_title_ar"] = r[9]
    if len(r) > 10:
        out["is_dept_quality_coordinator"] = int(r[10] or 0)
    return out


def _int_or_none(val):
    if val in (None, ""):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _fetch_user_rows(conn, *, scope_mode: str = "none", scope_department_id: int | None = None):
    cur = conn.cursor()
    try:
        if scope_mode == "empty":
            return []
        if scope_mode != "department" or scope_department_id is None:
            return cur.execute(f"{USER_LIST_SELECT} ORDER BY username").fetchall()
        dep = int(scope_department_id)
        return cur.execute(
            f"""
            SELECT DISTINCT u.username, u.role, u.student_id, u.instructor_id,
                   COALESCE(u.is_supervisor,0) AS is_supervisor,
                   COALESCE(u.is_active,1) AS is_active,
                   u.department_id,
                   COALESCE(u.is_system_account,0) AS is_system_account,
                   u.role_profile_id, u.display_title_ar,
                   COALESCE(u.is_dept_quality_coordinator,0) AS is_dept_quality_coordinator
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
    except Exception:
        if scope_mode == "empty":
            return []
        if scope_mode != "department" or scope_department_id is None:
            return cur.execute(f"{USER_LIST_SELECT_LEGACY} ORDER BY username").fetchall()
        dep = int(scope_department_id)
        return cur.execute(
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


def fetch_all_users_ordered(
    conn,
    *,
    scope_mode: str = "none",
    scope_department_id: int | None = None,
    exclude_system_accounts: bool = False,
) -> list[dict[str, Any]]:
    rows = _fetch_user_rows(conn, scope_mode=scope_mode, scope_department_id=scope_department_id)
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _user_row_to_dict(r)
        if exclude_system_accounts and int(d.get("is_system_account") or 0) == 1:
            continue
        if exclude_system_accounts and (d.get("role") or "").strip().lower() == "system_admin":
            continue
        out.append(d)
    return out


def fetch_user_row_by_username_ci(conn, username: str):
    cur = conn.cursor()
    try:
        return cur.execute(
            USER_LIST_SELECT.replace("FROM users", "FROM users WHERE lower(username) = lower(?)"),
            (username,),
        ).fetchone()
    except Exception:
        return cur.execute(
            "SELECT username, role, student_id, instructor_id, COALESCE(is_supervisor,0), COALESCE(is_active,1), department_id "
            "FROM users WHERE lower(username) = lower(?)",
            (username,),
        ).fetchone()


def fetch_user_row_after_write_ci(conn, username: str):
    return fetch_user_row_by_username_ci(conn, username)


def fetch_username_row_ci(conn, username: str):
    cur = conn.cursor()
    return cur.execute(
        "SELECT username FROM users WHERE lower(username) = lower(?) LIMIT 1",
        (username,),
    ).fetchone()
