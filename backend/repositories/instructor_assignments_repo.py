"""مستودع إسناد الأستاذ بأقسام متعددة."""
from __future__ import annotations

from backend.database.database import HOME_ASSIGNMENT_SECTION_ID, fetch_table_columns, is_postgresql, table_exists

_USER_SOURCES = ("user_ui", "manual")


def list_assignments_for_instructor(conn, instructor_id: int) -> list[dict]:
    if not table_exists(conn, "instructor_department_assignments"):
        return []
    cur = conn.cursor()
    ph = "%s" if is_postgresql() else "?"
    rows = cur.execute(
        f"""
        SELECT a.id, a.department_id, a.schedule_section_id, a.semester, a.is_primary, a.is_active,
               a.migration_source, d.code, d.name_ar
        FROM instructor_department_assignments a
        LEFT JOIN departments d ON d.id = a.department_id
        WHERE a.instructor_id = {ph}
        ORDER BY a.is_primary DESC, a.department_id, a.semester
        """,
        (int(instructor_id),),
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": r[0],
                "department_id": r[1],
                "schedule_section_id": r[2],
                "semester": r[3] or "",
                "is_primary": bool(r[4]),
                "is_active": bool(r[5]),
                "migration_source": r[6],
                "department_code": r[7],
                "department_name_ar": r[8],
            }
        )
    return out


def list_department_ids_for_instructors(conn, instructor_ids: list[int]) -> dict[int, list[int]]:
    """إرجاع dict instructor_id -> قائمة department_id الفريدة من الإسنادات النشطة."""
    if not instructor_ids or not table_exists(conn, "instructor_department_assignments"):
        return {}
    cur = conn.cursor()
    ph = "%s" if is_postgresql() else "?"
    placeholders = ",".join([ph] * len(instructor_ids))
    rows = cur.execute(
        f"""
        SELECT DISTINCT instructor_id, department_id
        FROM instructor_department_assignments
        WHERE instructor_id IN ({placeholders}) AND is_active = 1
        ORDER BY instructor_id, department_id
        """,
        tuple(int(x) for x in instructor_ids),
    ).fetchall()
    out: dict[int, list[int]] = {}
    for r in rows:
        iid, did = int(r[0]), int(r[1])
        out.setdefault(iid, []).append(did)
    return out


def delete_user_managed_assignments(conn, instructor_id: int) -> None:
    if not table_exists(conn, "instructor_department_assignments"):
        return
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            DELETE FROM instructor_department_assignments
            WHERE instructor_id = %s
              AND migration_source IN ('user_ui', 'manual')
            """,
            (int(instructor_id),),
        )
    else:
        cur.execute(
            """
            DELETE FROM instructor_department_assignments
            WHERE instructor_id = ?
              AND migration_source IN ('user_ui', 'manual')
            """,
            (int(instructor_id),),
        )


def upsert_user_assignment(
    conn,
    *,
    instructor_id: int,
    department_id: int,
    schedule_section_id: int = HOME_ASSIGNMENT_SECTION_ID,
    semester: str = "",
    is_primary: bool = False,
    source: str = "user_ui",
) -> None:
    if not table_exists(conn, "instructor_department_assignments"):
        return
    cur = conn.cursor()
    sem = (semester or "").strip()
    iid = int(instructor_id)
    did = int(department_id)
    sid = int(schedule_section_id)
    ip = 1 if is_primary else 0
    src = source if source in _USER_SOURCES else "user_ui"
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO instructor_department_assignments
            (instructor_id, department_id, schedule_section_id, semester,
             is_primary, is_active, migration_source)
            VALUES (%s, %s, %s, %s, %s, 1, %s)
            ON CONFLICT (instructor_id, department_id, schedule_section_id, semester)
            DO UPDATE SET is_primary = EXCLUDED.is_primary,
                          is_active = 1,
                          migration_source = EXCLUDED.migration_source,
                          updated_at = CURRENT_TIMESTAMP
            """,
            (iid, did, sid, sem, ip, src),
        )
    else:
        cur.execute(
            """
            INSERT INTO instructor_department_assignments
            (instructor_id, department_id, schedule_section_id, semester,
             is_primary, is_active, migration_source)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT (instructor_id, department_id, schedule_section_id, semester)
            DO UPDATE SET is_primary = excluded.is_primary,
                          is_active = 1,
                          migration_source = excluded.migration_source,
                          updated_at = CURRENT_TIMESTAMP
            """,
            (iid, did, sid, sem, ip, src),
        )


def replace_user_assignments_from_payload(conn, instructor_id: int, assignments: list[dict]) -> None:
    """يستبدل الإسنادات التي يديرها المستخدم بالقائمة المرسلة."""
    delete_user_managed_assignments(conn, instructor_id)
    for raw in assignments or []:
        try:
            did = int(raw.get("department_id"))
        except (TypeError, ValueError):
            continue
        try:
            sid = int(raw.get("schedule_section_id", HOME_ASSIGNMENT_SECTION_ID))
        except (TypeError, ValueError):
            sid = HOME_ASSIGNMENT_SECTION_ID
        sem = str(raw.get("semester") or "")
        is_pri = bool(raw.get("is_primary"))
        upsert_user_assignment(
            conn,
            instructor_id=instructor_id,
            department_id=did,
            schedule_section_id=sid,
            semester=sem,
            is_primary=is_pri,
            source="user_ui",
        )


def assignments_table_ready(conn) -> bool:
    return table_exists(conn, "instructor_department_assignments")


def list_assignment_department_details(conn, instructor_ids: list[int]) -> dict[int, list[dict]]:
    """تفاصيل الأقسام من جدول الإسناد لكل أستاذ (للعرض في القائمة)."""
    if not instructor_ids or not table_exists(conn, "instructor_department_assignments"):
        return {}
    cur = conn.cursor()
    ph = "%s" if is_postgresql() else "?"
    placeholders = ",".join([ph] * len(instructor_ids))
    ids = tuple(int(x) for x in instructor_ids)
    rows = cur.execute(
        f"""
        SELECT DISTINCT a.instructor_id, a.department_id, d.code, d.name_ar
        FROM instructor_department_assignments a
        LEFT JOIN departments d ON d.id = a.department_id
        WHERE a.instructor_id IN ({placeholders}) AND a.is_active = 1
        ORDER BY a.instructor_id, a.department_id
        """,
        ids,
    ).fetchall()
    out: dict[int, list[dict]] = {}
    seen: set[tuple[int, int]] = set()
    for r in rows:
        iid = int(r[0])
        did = int(r[1]) if r[1] is not None else None
        if did is None:
            continue
        key = (iid, did)
        if key in seen:
            continue
        seen.add(key)
        out.setdefault(iid, []).append(
            {
                "department_id": did,
                "department_code": r[2],
                "department_name_ar": r[3],
            }
        )
    return out
