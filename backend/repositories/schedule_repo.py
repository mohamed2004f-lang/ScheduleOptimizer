"""استعلامات جدول الجدول الدراسي المشتركة بين الخدمات."""
from __future__ import annotations

from typing import Any, Callable


def fetch_assigned_section_rows(
    cur,
    instructor_db_id: int,
    canonical_instructor_name: str,
    *,
    pk_col: str,
    normalize_name: Callable[[str | None], str],
) -> list[tuple]:
    """
    صفوف schedule المكلَّف بها الأستاذ:
    - تطابق مباشر على schedule.instructor_id؛
    - أو مطابقة الاسم النصّي بعد تطبيع الفراغات.
    """
    norm = normalize_name(canonical_instructor_name)
    q = f"""
        SELECT s.{pk_col} AS section_id,
               s.course_name,
               s.day,
               s.time,
               s.room,
               s.instructor,
               s.semester,
               s.instructor_id
        FROM schedule s
        WHERE s.instructor_id = ?
           OR (
                (s.instructor_id IS NULL OR s.instructor_id = 0)
                AND TRIM(COALESCE(s.instructor, '')) <> ''
           )
        ORDER BY s.semester, s.day, s.time, s.course_name
    """
    raw = cur.execute(q, (instructor_db_id,)).fetchall()
    out: list[tuple] = []
    for r in raw:
        sid, cn, day, tim, room, inst_txt, sem = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
        iid_col = r[7] if len(r) > 7 else None
        try:
            iid_int = int(iid_col) if iid_col is not None else None
        except (TypeError, ValueError):
            iid_int = None
        if iid_int == instructor_db_id:
            out.append((sid, cn, day, tim, room, inst_txt, sem))
            continue
        if (iid_int is None or iid_int == 0) and normalize_name(inst_txt) == norm:
            out.append((sid, cn, day, tim, room, inst_txt, sem))
    return out


def group_assigned_tuples_by_course(tuples: list[tuple]) -> list[dict[str, Any]]:
    """دمج صفوف الجدول لنفس المقرر في بطاقة واحدة."""
    grouped: dict[str, dict] = {}
    for t in tuples:
        sid, cn, day, tim, room, inst_txt, sem = t
        ck = (cn or "").strip().lower()
        if not ck:
            continue
        slot = {"day": day, "time": tim, "room": room, "section_id": int(sid)}
        bucket = grouped.get(ck)
        if not bucket:
            grouped[ck] = {
                "section_id": int(sid),
                "section_ids": [int(sid)],
                "course_name": (cn or "").strip(),
                "day": day,
                "time": tim,
                "room": room,
                "instructor": inst_txt,
                "semester": sem,
                "schedule_slots": [slot],
            }
            continue
        bucket["section_ids"].append(int(sid))
        bucket["schedule_slots"].append(slot)
        bucket["section_id"] = min(bucket["section_ids"])
        if len(bucket["schedule_slots"]) > 1:
            bucket["day"] = " — ".join(
                dict.fromkeys(
                    f"{s.get('day') or ''} {s.get('time') or ''}".strip()
                    for s in bucket["schedule_slots"]
                )
            )
            rooms = [str(s.get("room") or "").strip() for s in bucket["schedule_slots"] if s.get("room")]
            bucket["room"] = " / ".join(dict.fromkeys(r for r in rooms if r)) or room
    return list(grouped.values())


def _course_name_keys(course_names: list[str]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for raw in course_names:
        ck = str(raw or "").strip().lower()
        if not ck or ck in seen:
            continue
        seen.add(ck)
        keys.append(ck)
    return keys


def count_students_grouped_by_course(cur, course_names: list[str]) -> dict[str, int]:
    """عدد الطلاب المسجّلين لكل مقرر (مفتاح الاسم بعد trim/lower)."""
    keys = _course_name_keys(course_names)
    if not keys:
        return {}
    ph = ",".join(["?"] * len(keys))
    rows = cur.execute(
        f"""
        SELECT LOWER(TRIM(course_name)) AS ck, COUNT(DISTINCT student_id) AS cnt
        FROM registrations
        WHERE LOWER(TRIM(course_name)) IN ({ph})
        GROUP BY LOWER(TRIM(course_name))
        """,
        tuple(keys),
    ).fetchall()
    return {r[0]: int(r[1] or 0) for r in rows if r and r[0]}


def count_distinct_students_for_courses(cur, course_names: list[str]) -> int:
    """عدد الطلاب المميزين عبر مجموعة مقررات."""
    keys = _course_name_keys(course_names)
    if not keys:
        return 0
    ph = ",".join(["?"] * len(keys))
    row = cur.execute(
        f"SELECT COUNT(DISTINCT student_id) FROM registrations WHERE LOWER(TRIM(course_name)) IN ({ph})",
        tuple(keys),
    ).fetchone()
    return int(row[0]) if row else 0


def fetch_schedule_rows_with_student_counts(
    cur,
    *,
    pk_col: str,
    department_id: int | None = None,
    include_teaching_groups: bool = False,
    registrations_has_teaching_group: bool = False,
) -> list[tuple]:
    """
    صفوف الجدول مع عدد الطلاب المسجّلين.
    الفلترة حسب القسم ومجموعات التدريس اختيارية حتى يبقى مسار ScheduleService كما هو.
    """
    dept_where = ""
    dept_params: tuple = ()
    if department_id is not None:
        dept_where = " AND s.department_id = ? "
        dept_params = (department_id,)
    tg_join = ""
    tg_select = ""
    reg_join = "LEFT JOIN registrations r ON LOWER(TRIM(s.course_name)) = LOWER(TRIM(r.course_name))"
    if include_teaching_groups:
        tg_join = """
                LEFT JOIN teaching_groups tg ON tg.id = s.teaching_group_id AND tg.is_active = 1
                LEFT JOIN departments td ON td.id = COALESCE(tg.department_id, s.department_id)
                LEFT JOIN instructors ti ON ti.id = COALESCE(tg.instructor_id, s.instructor_id)
                """
        tg_select = """,
                    s.teaching_group_id,
                    s.department_id,
                    COALESCE(tg.group_code, '—') AS tg_group_code,
                    COALESCE(td.name_ar, td.code, '') AS tg_department_name,
                    COALESCE(ti.name, s.instructor, '') AS tg_instructor_name
                """
        if registrations_has_teaching_group:
            reg_join = """
                LEFT JOIN registrations r ON LOWER(TRIM(s.course_name)) = LOWER(TRIM(r.course_name))
                    AND (
                        s.teaching_group_id IS NULL
                        OR r.teaching_group_id = s.teaching_group_id
                    )
                    """
    group_by_tg = ""
    if tg_select:
        group_by_tg = """,
                    s.teaching_group_id, s.department_id,
                    tg.group_code, td.name_ar, td.code, ti.name
                """
    return cur.execute(
        f"""
                SELECT
                    s.{pk_col} AS section_id,
                    s.course_name,
                    s.day,
                    s.time,
                    s.room,
                    s.instructor,
                    s.semester,
                    s.instructor_id,
                    COUNT(DISTINCT r.student_id) AS student_count
                    {tg_select}
                FROM schedule s
                {reg_join}
                {tg_join}
                WHERE 1=1 {dept_where}
                GROUP BY s.{pk_col}, s.course_name, s.day, s.time, s.room, s.instructor, s.semester, s.instructor_id
                    {group_by_tg}
                ORDER BY s.{pk_col}
                """,
        dept_params,
    ).fetchall()

