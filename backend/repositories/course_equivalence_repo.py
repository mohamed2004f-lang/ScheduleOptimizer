"""مستودع مجموعات تكافؤ المقررات بين الأقسام."""
from __future__ import annotations

from backend.database.database import is_postgresql, table_exists


def list_groups(conn) -> list[dict]:
    if not table_exists(conn, "course_equivalence_groups"):
        return []
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, group_key, title, is_active, created_at
        FROM course_equivalence_groups
        ORDER BY group_key
        """
    ).fetchall()
    return [
        {
            "id": r[0],
            "group_key": r[1],
            "title": r[2] or "",
            "is_active": bool(r[3]),
            "created_at": r[4],
        }
        for r in rows
    ]


def list_items_for_group(conn, group_id: int) -> list[dict]:
    if not table_exists(conn, "course_equivalence_items"):
        return []
    cur = conn.cursor()
    ph = "%s" if is_postgresql() else "?"
    rows = cur.execute(
        f"""
        SELECT id, group_id, department_id, course_name, course_code,
               program_course_id, is_active, created_at
        FROM course_equivalence_items
        WHERE group_id = {ph}
        ORDER BY department_id, course_name
        """,
        (int(group_id),),
    ).fetchall()
    return [
        {
            "id": r[0],
            "group_id": r[1],
            "department_id": r[2],
            "course_name": r[3],
            "course_code": r[4] or "",
            "program_course_id": r[5],
            "is_active": bool(r[6]),
            "created_at": r[7],
        }
        for r in rows
    ]


def expand_course_names_for_department(
    conn, department_id: int, course_names: set[str]
) -> set[str]:
    """
    يوسّع مجموعة أسماء المقررات بإضافة كل المقررات في مجموعات التكافؤ
    التي تضم أحد هذه الأسماء ضمن نفس department_id.
    """
    if not course_names or not table_exists(conn, "course_equivalence_items"):
        return set(course_names)
    dept_id = int(department_id)
    cur = conn.cursor()
    ph = "%s" if is_postgresql() else "?"
    placeholders = ",".join([ph] * len(course_names))
    params = [dept_id, *list(course_names)]
    rows = cur.execute(
        f"""
        SELECT DISTINCT group_id FROM course_equivalence_items
        WHERE department_id = {ph} AND is_active = 1 AND course_name IN ({placeholders})
        """,
        tuple(params),
    ).fetchall()
    gids = [int(r[0]) for r in rows]
    if not gids:
        return set(course_names)
    ph2 = ",".join([ph] * len(gids))
    rows2 = cur.execute(
        f"""
        SELECT DISTINCT course_name FROM course_equivalence_items
        WHERE department_id = {ph} AND is_active = 1 AND group_id IN ({ph2})
        """,
        tuple([dept_id, *gids]),
    ).fetchall()
    expanded = set(course_names)
    for r in rows2:
        expanded.add(str(r[0]))
    return expanded


def save_group(conn, *, group_key: str, title: str | None, is_active: bool = True) -> int:
    if not table_exists(conn, "course_equivalence_groups"):
        return 0
    gk = (group_key or "").strip()
    if not gk:
        raise ValueError("group_key مطلوب")
    cur = conn.cursor()
    tit = (title or "").strip()
    ia = 1 if is_active else 0
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO course_equivalence_groups (group_key, title, is_active)
            VALUES (%s, %s, %s)
            ON CONFLICT (group_key) DO UPDATE SET title = EXCLUDED.title,
              is_active = EXCLUDED.is_active
            RETURNING id
            """,
            (gk, tit, ia),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
    cur.execute(
        """
        INSERT INTO course_equivalence_groups (group_key, title, is_active)
        VALUES (?, ?, ?)
        ON CONFLICT (group_key) DO UPDATE SET title = excluded.title,
          is_active = excluded.is_active
        """,
        (gk, tit, ia),
    )
    rid = cur.execute(
        "SELECT id FROM course_equivalence_groups WHERE group_key = ? LIMIT 1", (gk,)
    ).fetchone()
    return int(rid[0]) if rid else 0


def save_item(
    conn,
    *,
    group_id: int,
    department_id: int,
    course_name: str,
    course_code: str | None = None,
    program_course_id: int | None = None,
    is_active: bool = True,
) -> None:
    if not table_exists(conn, "course_equivalence_items"):
        return
    cn = (course_name or "").strip()
    if not cn:
        raise ValueError("course_name مطلوب")
    cc = (course_code or "").strip()
    cur = conn.cursor()
    gid = int(group_id)
    did = int(department_id)
    pc = program_course_id
    ia = 1 if is_active else 0
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO course_equivalence_items
            (group_id, department_id, course_name, course_code, program_course_id, is_active)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (group_id, department_id, course_name)
            DO UPDATE SET course_code = EXCLUDED.course_code,
              program_course_id = EXCLUDED.program_course_id,
              is_active = EXCLUDED.is_active
            """,
            (gid, did, cn, cc, pc, ia),
        )
    else:
        cur.execute(
            """
            INSERT INTO course_equivalence_items
            (group_id, department_id, course_name, course_code, program_course_id, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (group_id, department_id, course_name)
            DO UPDATE SET course_code = excluded.course_code,
              program_course_id = excluded.program_course_id,
              is_active = excluded.is_active
            """,
            (gid, did, cn, cc, pc, ia),
        )


def delete_item(conn, item_id: int) -> bool:
    if not table_exists(conn, "course_equivalence_items"):
        return False
    cur = conn.cursor()
    ph = "%s" if is_postgresql() else "?"
    cur.execute(f"DELETE FROM course_equivalence_items WHERE id = {ph}", (int(item_id),))
    return cur.rowcount > 0


def delete_group(conn, group_id: int) -> bool:
    if not table_exists(conn, "course_equivalence_groups"):
        return False
    cur = conn.cursor()
    ph = "%s" if is_postgresql() else "?"
    cur.execute(f"DELETE FROM course_equivalence_groups WHERE id = {ph}", (int(group_id),))
    return cur.rowcount > 0
