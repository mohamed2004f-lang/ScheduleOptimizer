"""حقن حصص الاتجاه العام في جداول الأقسام التخصصية + اختيار المجموعة ونقل التسجيلات."""

from __future__ import annotations

import logging
from typing import Any

from backend.database.database import fetch_table_columns, table_exists
from backend.services.teaching_groups import (
    count_registrations_for_teaching_group,
    list_teaching_groups,
)

logger = logging.getLogger(__name__)


def ensure_bindings_schema(conn) -> None:
    """إنشاء جدول ربط القسم ← مجموعة GENERAL إن لم يوجد."""
    if table_exists(conn, "department_general_group_bindings"):
        return
    cur = conn.cursor()
    try:
        from backend.database.database import is_postgresql

        if is_postgresql():
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS department_general_group_bindings (
                    id BIGSERIAL PRIMARY KEY,
                    semester TEXT NOT NULL,
                    consumer_department_id BIGINT NOT NULL REFERENCES departments(id)
                        ON DELETE RESTRICT ON UPDATE CASCADE,
                    course_name TEXT NOT NULL,
                    teaching_group_id BIGINT NOT NULL REFERENCES teaching_groups(id)
                        ON DELETE RESTRICT ON UPDATE CASCADE,
                    updated_by TEXT DEFAULT '',
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (semester, consumer_department_id, course_name)
                )
                """
            )
        else:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS department_general_group_bindings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    semester TEXT NOT NULL,
                    consumer_department_id INTEGER NOT NULL,
                    course_name TEXT NOT NULL,
                    teaching_group_id INTEGER NOT NULL,
                    updated_by TEXT DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (semester, consumer_department_id, course_name),
                    FOREIGN KEY (consumer_department_id) REFERENCES departments(id)
                        ON DELETE RESTRICT ON UPDATE CASCADE,
                    FOREIGN KEY (teaching_group_id) REFERENCES teaching_groups(id)
                        ON DELETE RESTRICT ON UPDATE CASCADE
                )
                """
            )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_dept_gen_bind_sem_dept "
            "ON department_general_group_bindings(semester, consumer_department_id)"
        )
        try:
            conn.commit()
        except Exception:
            pass
    except Exception:
        logger.exception("ensure department_general_group_bindings failed")


def _row_get(row, key: str, idx: int, default=None):
    if row is None:
        return default
    if hasattr(row, "keys"):
        try:
            if key in row.keys():
                return row[key]
        except Exception:
            pass
    try:
        return row[idx]
    except Exception:
        return default


def _normalize_semester(conn, semester: str | None) -> str:
    sem = (semester or "").strip()
    if sem:
        return sem
    from backend.services.utilities import get_current_term

    tname, tyear = get_current_term(conn=conn)
    return f"{(tname or '').strip()} {(tyear or '').strip()}".strip()


def _general_dept_id(conn) -> int | None:
    from backend.core.department_scope_policy import resolve_college_general_department_id

    gid = resolve_college_general_department_id(conn)
    return int(gid) if gid else None


def is_specialty_consumer_department(conn, department_id: int | None) -> bool:
    """قسم تخصصي (ليس GENERAL) يمكنه استقبال overlay."""
    if not department_id or int(department_id) <= 0:
        return False
    gen = _general_dept_id(conn)
    if not gen:
        return True
    return int(department_id) != int(gen)


def list_bindings(
    conn,
    *,
    semester: str,
    consumer_department_id: int,
) -> dict[str, int]:
    """course_name_lower → teaching_group_id من الربط الصريح."""
    ensure_bindings_schema(conn)
    if not table_exists(conn, "department_general_group_bindings"):
        return {}
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT course_name, teaching_group_id
        FROM department_general_group_bindings
        WHERE semester = ? AND consumer_department_id = ?
        """,
        (semester, int(consumer_department_id)),
    ).fetchall() or []
    out: dict[str, int] = {}
    for r in rows:
        cname = str(_row_get(r, "course_name", 0, "") or "").strip().lower()
        gid = int(_row_get(r, "teaching_group_id", 1, 0) or 0)
        if cname and gid > 0:
            out[cname] = gid
    return out


def _registration_group_counts_for_dept(
    conn,
    *,
    semester: str,
    consumer_department_id: int,
    general_department_id: int,
) -> dict[str, dict[int, int]]:
    """course_name_lower → {teaching_group_id: count} لطلبة القسم على مجموعات GENERAL."""
    if not table_exists(conn, "registrations") or not table_exists(conn, "teaching_groups"):
        return {}
    reg_cols = {c.lower() for c in fetch_table_columns(conn, "registrations")}
    if "teaching_group_id" not in reg_cols:
        return {}
    from backend.core.enrollment_status_policy import operational_status_sql

    active_stu = operational_status_sql("st")
    cur = conn.cursor()
    # فلترة الفصل: إن وُجد عمود semester على التسجيلات
    sem_clause = ""
    params: list[Any] = [int(consumer_department_id), int(general_department_id)]
    if "semester" in reg_cols:
        sem_clause = " AND (COALESCE(TRIM(r.semester), '') = '' OR lower(trim(r.semester)) = lower(trim(?))) "
        params.append(semester)
    rows = cur.execute(
        f"""
        SELECT lower(trim(r.course_name)) AS cname,
               r.teaching_group_id AS gid,
               COUNT(DISTINCT r.student_id) AS cnt
        FROM registrations r
        INNER JOIN students st ON st.student_id = r.student_id AND {active_stu}
        INNER JOIN teaching_groups tg ON tg.id = r.teaching_group_id AND tg.is_active = 1
        WHERE st.department_id = ?
          AND tg.department_id = ?
          AND r.teaching_group_id IS NOT NULL
          {sem_clause}
        GROUP BY lower(trim(r.course_name)), r.teaching_group_id
        """,
        tuple(params),
    ).fetchall() or []
    out: dict[str, dict[int, int]] = {}
    for r in rows:
        cname = str(_row_get(r, "cname", 0, "") or "").strip().lower()
        gid = int(_row_get(r, "gid", 1, 0) or 0)
        cnt = int(_row_get(r, "cnt", 2, 0) or 0)
        if not cname or gid <= 0 or cnt <= 0:
            continue
        out.setdefault(cname, {})[gid] = cnt
    return out


def resolve_effective_general_groups(
    conn,
    *,
    consumer_department_id: int,
    semester: str | None = None,
) -> dict[str, Any]:
    """
    يحدّد مجموعة GENERAL الفعّالة لكل مقرر للقسم المستهلك.
    يفضّل الربط الصريح؛ وإلا أغلبية تسجيلات طلبة القسم.
    """
    sem = _normalize_semester(conn, semester)
    gen_id = _general_dept_id(conn)
    if not gen_id or not is_specialty_consumer_department(conn, consumer_department_id):
        return {
            "semester": sem,
            "by_course": {},
            "split_warnings": [],
            "bindings": {},
        }
    bindings = list_bindings(conn, semester=sem, consumer_department_id=int(consumer_department_id))
    reg_counts = _registration_group_counts_for_dept(
        conn,
        semester=sem,
        consumer_department_id=int(consumer_department_id),
        general_department_id=int(gen_id),
    )
    by_course: dict[str, dict[str, Any]] = {}
    split_warnings: list[dict[str, Any]] = []
    all_courses = set(bindings.keys()) | set(reg_counts.keys())
    for cname in sorted(all_courses):
        counts = reg_counts.get(cname) or {}
        bound = bindings.get(cname)
        if bound:
            by_course[cname] = {
                "course_name": cname,
                "teaching_group_id": int(bound),
                "source": "binding",
                "dept_enrolled": int(counts.get(int(bound), 0)),
                "group_counts": {str(k): int(v) for k, v in counts.items()},
            }
            continue
        if not counts:
            continue
        if len(counts) > 1:
            split_warnings.append(
                {
                    "course_name": cname,
                    "group_counts": {str(k): int(v) for k, v in counts.items()},
                    "message": "طلابك موزّعون على أكثر من مجموعة اتجاه عام — اختر مجموعة موحّدة",
                }
            )
        best_gid = max(counts.keys(), key=lambda g: (counts[g], -int(g)))
        by_course[cname] = {
            "course_name": cname,
            "teaching_group_id": int(best_gid),
            "source": "registrations",
            "dept_enrolled": int(counts[best_gid]),
            "group_counts": {str(k): int(v) for k, v in counts.items()},
        }
    return {
        "semester": sem,
        "by_course": by_course,
        "split_warnings": split_warnings,
        "bindings": bindings,
        "general_department_id": int(gen_id),
    }


def count_dept_students_on_group(
    conn,
    *,
    teaching_group_id: int,
    consumer_department_id: int,
) -> int:
    if not table_exists(conn, "registrations"):
        return 0
    reg_cols = {c.lower() for c in fetch_table_columns(conn, "registrations")}
    if "teaching_group_id" not in reg_cols:
        return 0
    from backend.core.enrollment_status_policy import operational_status_sql

    active_stu = operational_status_sql("st")
    row = conn.cursor().execute(
        f"""
        SELECT COUNT(DISTINCT r.student_id)
        FROM registrations r
        INNER JOIN students st ON st.student_id = r.student_id AND {active_stu}
        WHERE r.teaching_group_id = ? AND st.department_id = ?
        """,
        (int(teaching_group_id), int(consumer_department_id)),
    ).fetchone()
    return int(_row_get(row, 0, 0, 0) or 0)


def fetch_overlay_schedule_items(
    conn,
    *,
    consumer_department_id: int,
    semester: str | None = None,
    pk_col: str = "id",
) -> list[dict[str, Any]]:
    """صفوف schedule من مجموعات GENERAL الفعّالة — قراءة فقط، بدون نسخ."""
    if not is_specialty_consumer_department(conn, consumer_department_id):
        return []
    if not table_exists(conn, "schedule") or not table_exists(conn, "teaching_groups"):
        return []
    resolved = resolve_effective_general_groups(
        conn,
        consumer_department_id=int(consumer_department_id),
        semester=semester,
    )
    by_course = resolved.get("by_course") or {}
    group_ids = sorted(
        {
            int(v["teaching_group_id"])
            for v in by_course.values()
            if int(v.get("teaching_group_id") or 0) > 0
        }
    )
    if not group_ids:
        return []
    gen_id = int(resolved.get("general_department_id") or 0)
    placeholders = ",".join("?" for _ in group_ids)
    cur = conn.cursor()
    scols = {c.lower() for c in fetch_table_columns(conn, "schedule")}
    if "teaching_group_id" not in scols:
        return []
    rows = cur.execute(
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
            s.teaching_group_id,
            s.department_id,
            COALESCE(tg.group_code, '—') AS group_code,
            COALESCE(td.name_ar, td.code, '') AS tg_department_name,
            COALESCE(ti.name, s.instructor, '') AS tg_instructor_name
        FROM schedule s
        INNER JOIN teaching_groups tg ON tg.id = s.teaching_group_id AND tg.is_active = 1
        LEFT JOIN departments td ON td.id = tg.department_id
        LEFT JOIN instructors ti ON ti.id = COALESCE(tg.instructor_id, s.instructor_id)
        WHERE s.teaching_group_id IN ({placeholders})
          AND tg.department_id = ?
        ORDER BY s.{pk_col}
        """,
        tuple(group_ids) + (gen_id,),
    ).fetchall() or []

    from backend.services import teaching_groups as tg_svc

    items: list[dict[str, Any]] = []
    for r in rows:
        cname = str(_row_get(r, "course_name", 1, "") or "").strip()
        gid = int(_row_get(r, "teaching_group_id", 8, 0) or 0)
        meta = by_course.get(cname.lower()) or {}
        # تجاهل حصص مجموعات غير الفعّالة لنفس المقرر إن وُجدت
        if meta and int(meta.get("teaching_group_id") or 0) != gid:
            continue
        gcode = str(_row_get(r, "group_code", 10, "—") or "—")
        dept_count = count_dept_students_on_group(
            conn,
            teaching_group_id=gid,
            consumer_department_id=int(consumer_department_id),
        )
        item = {
            "section_id": int(_row_get(r, "section_id", 0, 0) or 0),
            "course_name": cname,
            "day": str(_row_get(r, "day", 2, "") or ""),
            "time": str(_row_get(r, "time", 3, "") or ""),
            "room": str(_row_get(r, "room", 4, "") or ""),
            "instructor": str(_row_get(r, "instructor", 5, "") or ""),
            "semester": str(_row_get(r, "semester", 6, "") or ""),
            "instructor_id": _row_get(r, "instructor_id", 7),
            "student_count": dept_count,
            "teaching_group_id": gid,
            "department_id": int(_row_get(r, "department_id", 9, gen_id) or gen_id),
            "group_code": gcode,
            "group_code_label": tg_svc.group_code_label(gcode),
            "teaching_group_label": tg_svc.format_teaching_group_label(
                course_name=cname,
                department_name=str(_row_get(r, "tg_department_name", 11, "") or ""),
                group_code=gcode,
                instructor_name=str(
                    _row_get(r, "tg_instructor_name", 12, "") or _row_get(r, "instructor", 5, "") or ""
                ),
            ),
            "is_overlay_general": True,
            "is_college_general": True,
            "overlay_source": meta.get("source") or "registrations",
        }
        items.append(item)
    return items


def append_overlay_rows(
    conn,
    result: list[dict[str, Any]],
    *,
    consumer_department_id: int | None,
    semester: str | None = None,
    pk_col: str = "id",
    term_match_ctx=None,
) -> list[dict[str, Any]]:
    """يلحق صفوف overlay بعد صفوف القسم ويُثري حقول المرحلة."""
    if not consumer_department_id or not is_specialty_consumer_department(conn, consumer_department_id):
        return result
    try:
        overlay = fetch_overlay_schedule_items(
            conn,
            consumer_department_id=int(consumer_department_id),
            semester=semester,
            pk_col=pk_col,
        )
    except Exception:
        logger.exception("fetch_overlay_schedule_items failed")
        return result
    if not overlay:
        return result
    if term_match_ctx is not None:
        from backend.services.term_engine import schedule_semester_matches_term_context

        overlay = [
            x
            for x in overlay
            if schedule_semester_matches_term_context(x.get("semester"), term_match_ctx)
        ]
    # تجنب تكرار section_id إن وُجد بالخطأ في نتيجة القسم
    existing_ids = {
        int(x.get("section_id") or 0)
        for x in result
        if int(x.get("section_id") or 0) > 0
    }
    for item in overlay:
        sid = int(item.get("section_id") or 0)
        if sid and sid in existing_ids:
            continue
        result.append(item)
    try:
        from backend.services import teaching_groups as tg_svc

        tg_svc.enrich_schedule_rows_instructor_team(conn, [x for x in result if x.get("is_overlay_general")])
    except Exception:
        pass
    try:
        from backend.core.schedule_stage_layout import (
            enrich_schedule_row_stage_fields,
            load_course_codes_by_name,
        )

        overlay_items = [x for x in result if x.get("is_overlay_general")]
        code_map = load_course_codes_by_name(
            conn, [str(x.get("course_name") or "") for x in overlay_items]
        )
        for item in overlay_items:
            enrich_schedule_row_stage_fields(conn, item, course_code_by_name=code_map)
            item["is_overlay_general"] = True
            item["is_college_general"] = True
    except Exception:
        logger.exception("overlay stage enrichment failed")
    return result


def list_general_group_options(
    conn,
    *,
    course_name: str,
    semester: str | None = None,
    consumer_department_id: int,
) -> dict[str, Any]:
    """خيارات مجموعات GENERAL لمقرر مع الأوقات والسعة وعدد طلبة القسم."""
    cname = (course_name or "").strip()
    sem = _normalize_semester(conn, semester)
    gen_id = _general_dept_id(conn)
    if not cname or not gen_id:
        return {"course_name": cname, "semester": sem, "options": [], "split_warning": None}
    from backend.core.department_scope_policy import course_is_college_general

    if not course_is_college_general(conn, cname):
        return {
            "course_name": cname,
            "semester": sem,
            "options": [],
            "error": "المقرر ليس من الاتجاه العام",
        }
    groups = list_teaching_groups(
        conn, semester=sem, department_id=int(gen_id), course_name=cname
    )
    resolved = resolve_effective_general_groups(
        conn, consumer_department_id=int(consumer_department_id), semester=sem
    )
    current = (resolved.get("by_course") or {}).get(cname.lower())
    split_warning = None
    for w in resolved.get("split_warnings") or []:
        if str(w.get("course_name") or "").lower() == cname.lower():
            split_warning = w
            break
    options = []
    cur = conn.cursor()
    for g in groups:
        gid = int(g.get("id") or 0)
        if not gid:
            continue
        slots = cur.execute(
            """
            SELECT day, time, room
            FROM schedule
            WHERE teaching_group_id = ?
            ORDER BY day, time
            """,
            (gid,),
        ).fetchall() or []
        slot_list = [
            {
                "day": str(_row_get(s, "day", 0, "") or ""),
                "time": str(_row_get(s, "time", 1, "") or ""),
                "room": str(_row_get(s, "room", 2, "") or ""),
            }
            for s in slots
        ]
        cap = g.get("capacity_max")
        enrolled = count_registrations_for_teaching_group(conn, gid)
        dept_n = count_dept_students_on_group(
            conn, teaching_group_id=gid, consumer_department_id=int(consumer_department_id)
        )
        options.append(
            {
                "teaching_group_id": gid,
                "group_code": g.get("group_code"),
                "group_kind": g.get("group_kind"),
                "instructor_name": g.get("instructor_name") or g.get("instructor") or "",
                "capacity_max": int(cap) if cap not in (None, "") else None,
                "enrolled_count": enrolled,
                "dept_enrolled_count": dept_n,
                "slots": slot_list,
                "is_current": bool(current and int(current.get("teaching_group_id") or 0) == gid),
            }
        )
    return {
        "course_name": cname,
        "semester": sem,
        "options": options,
        "current_teaching_group_id": int(current["teaching_group_id"]) if current else None,
        "split_warning": split_warning,
        "binding_source": (current or {}).get("source"),
    }


def _dept_students_registered_for_course(
    conn,
    *,
    course_name: str,
    semester: str,
    consumer_department_id: int,
) -> list[str]:
    if not table_exists(conn, "registrations"):
        return []
    from backend.core.enrollment_status_policy import operational_status_sql

    active_stu = operational_status_sql("st")
    reg_cols = {c.lower() for c in fetch_table_columns(conn, "registrations")}
    cname = (course_name or "").strip()
    sem_clause = ""
    params: list[Any] = [cname, int(consumer_department_id)]
    if "semester" in reg_cols:
        sem_clause = " AND (COALESCE(TRIM(r.semester), '') = '' OR lower(trim(r.semester)) = lower(trim(?))) "
        params.append(semester)
    rows = conn.cursor().execute(
        f"""
        SELECT DISTINCT r.student_id
        FROM registrations r
        INNER JOIN students st ON st.student_id = r.student_id AND {active_stu}
        WHERE lower(trim(r.course_name)) = lower(trim(?))
          AND st.department_id = ?
          {sem_clause}
        """,
        tuple(params),
    ).fetchall() or []
    return [str(_row_get(r, "student_id", 0, "") or "").strip() for r in rows if _row_get(r, "student_id", 0)]


def _slots_for_teaching_group(conn, teaching_group_id: int) -> list[tuple[str, str]]:
    rows = conn.cursor().execute(
        "SELECT day, time FROM schedule WHERE teaching_group_id = ?",
        (int(teaching_group_id),),
    ).fetchall() or []
    return [
        (str(_row_get(r, "day", 0, "") or "").strip(), str(_row_get(r, "time", 1, "") or "").strip())
        for r in rows
    ]


def _student_other_slots(
    conn,
    *,
    student_id: str,
    semester: str,
    exclude_course_name: str,
) -> list[tuple[str, str, str]]:
    """(day, time, course_name) لحصص الطالب الأخرى في الفصل."""
    from backend.core.enrollment_status_policy import operational_status_sql

    active_stu = operational_status_sql("st")
    reg_cols = {c.lower() for c in fetch_table_columns(conn, "registrations")}
    scols = {c.lower() for c in fetch_table_columns(conn, "schedule")}
    if "teaching_group_id" not in reg_cols or "teaching_group_id" not in scols:
        return []
    sem_clause = ""
    params: list[Any] = [student_id, exclude_course_name]
    if "semester" in reg_cols:
        sem_clause = " AND (COALESCE(TRIM(r.semester), '') = '' OR lower(trim(r.semester)) = lower(trim(?))) "
        params.append(semester)
    rows = conn.cursor().execute(
        f"""
        SELECT s.day, s.time, s.course_name
        FROM registrations r
        INNER JOIN students st ON st.student_id = r.student_id AND {active_stu}
        INNER JOIN schedule s ON s.teaching_group_id = r.teaching_group_id
        WHERE r.student_id = ?
          AND lower(trim(r.course_name)) <> lower(trim(?))
          AND r.teaching_group_id IS NOT NULL
          {sem_clause}
        """,
        tuple(params),
    ).fetchall() or []
    out = []
    for r in rows:
        out.append(
            (
                str(_row_get(r, "day", 0, "") or "").strip(),
                str(_row_get(r, "time", 1, "") or "").strip(),
                str(_row_get(r, "course_name", 2, "") or "").strip(),
            )
        )
    return out


def _time_ranges_overlap(t1: str, t2: str) -> bool:
    from backend.services.schedule import _parse_time_range_to_minutes, _ranges_overlap

    a1, a2 = _parse_time_range_to_minutes(t1)
    b1, b2 = _parse_time_range_to_minutes(t2)
    return _ranges_overlap(a1, a2, b1, b2)


def find_student_conflicts_for_group(
    conn,
    *,
    student_ids: list[str],
    teaching_group_id: int,
    semester: str,
    course_name: str,
) -> list[dict[str, Any]]:
    target_slots = _slots_for_teaching_group(conn, teaching_group_id)
    if not target_slots:
        return []
    conflicts: list[dict[str, Any]] = []
    for sid in student_ids:
        others = _student_other_slots(
            conn, student_id=sid, semester=semester, exclude_course_name=course_name
        )
        for day, time in target_slots:
            for od, ot, oc in others:
                if day and od and day != od:
                    continue
                if day == od and _time_ranges_overlap(time, ot):
                    conflicts.append(
                        {
                            "student_id": sid,
                            "day": day,
                            "time": time,
                            "conflicts_with": oc,
                            "conflict_time": ot,
                        }
                    )
    return conflicts


def _exams_note_for_migration(
    conn,
    *,
    course_name: str,
    from_group_ids: list[int],
    to_group_id: int,
) -> str | None:
    if not table_exists(conn, "exams"):
        return None
    cols = {c.lower() for c in fetch_table_columns(conn, "exams")}
    if "teaching_group_id" not in cols:
        return None
    ids = [int(x) for x in from_group_ids if int(x) > 0 and int(x) != int(to_group_id)]
    if not ids:
        return None
    placeholders = ",".join("?" for _ in ids)
    row = conn.cursor().execute(
        f"""
        SELECT COUNT(*) FROM exams
        WHERE teaching_group_id IN ({placeholders})
          AND lower(trim(course_name)) = lower(trim(?))
        """,
        tuple(ids) + ((course_name or "").strip(),),
    ).fetchone()
    n = int(_row_get(row, 0, 0, 0) or 0)
    if n <= 0:
        return None
    return (
        f"تنبيه: يوجد {n} امتحان مرتبط بالمجموعة السابقة لنفس المقرر — "
        "راجع جداول الامتحانات بعد النقل (لم يُحذف امتحان المجموعة الأصلية)."
    )


def select_general_group_for_department(
    conn,
    *,
    course_name: str,
    semester: str | None,
    teaching_group_id: int,
    consumer_department_id: int,
    actor: str | None = None,
    force_admin: bool = False,
    allow_conflicts: bool = False,
) -> dict[str, Any]:
    """
    ينقل تسجيلات طلبة القسم إلى مجموعة GENERAL المختارة ويحدّث الربط.
    معاملة واحدة + فحص سعة + تعارضات أوقات.
    """
    cname = (course_name or "").strip()
    sem = _normalize_semester(conn, semester)
    gid = int(teaching_group_id or 0)
    dept = int(consumer_department_id or 0)
    if not cname or gid <= 0 or dept <= 0:
        raise ValueError("course_name و teaching_group_id و department مطلوبون")
    if not is_specialty_consumer_department(conn, dept):
        raise ValueError("اختيار المجموعة متاح للأقسام التخصصية فقط")
    gen_id = _general_dept_id(conn)
    if not gen_id:
        raise ValueError("قسم الاتجاه العام غير معرّف")

    from backend.core.department_scope_policy import course_is_college_general
    from backend.services.utilities import get_schedule_published_at, log_activity

    if not course_is_college_general(conn, cname):
        raise ValueError("المقرر ليس من الاتجاه العام")

    # قفل بعد النشر: admin فقط
    if not force_admin and get_schedule_published_at(conn) is not None:
        raise PermissionError("الجدول معتمد/منشور — اختيار المجموعة متاح للمسؤول فقط")

    ensure_bindings_schema(conn)
    cur = conn.cursor()
    g = cur.execute(
        """
        SELECT id, department_id, capacity_max, is_active, group_code
        FROM teaching_groups
        WHERE id = ? LIMIT 1
        """,
        (gid,),
    ).fetchone()
    if not g:
        raise ValueError("مجموعة التدريس غير موجودة")
    if int(_row_get(g, "department_id", 1, 0) or 0) != int(gen_id):
        raise ValueError("المجموعة المختارة ليست من الاتجاه العام")
    if int(_row_get(g, "is_active", 3, 1) or 0) != 1:
        raise ValueError("المجموعة غير نشطة")

    student_ids = _dept_students_registered_for_course(
        conn, course_name=cname, semester=sem, consumer_department_id=dept
    )
    # من هم بالفعل على المجموعة الهدف
    already: set[str] = set()
    if student_ids:
        placeholders = ",".join("?" for _ in student_ids)
        rows = cur.execute(
            f"""
            SELECT student_id FROM registrations
            WHERE teaching_group_id = ?
              AND lower(trim(course_name)) = lower(trim(?))
              AND student_id IN ({placeholders})
            """,
            (gid, cname, *student_ids),
        ).fetchall() or []
        already = {str(_row_get(r, "student_id", 0, "") or "") for r in rows}

    to_move = [s for s in student_ids if s not in already]
    cap_raw = _row_get(g, "capacity_max", 2, None)
    capacity_max = int(cap_raw) if cap_raw not in (None, "") else None
    enrolled = count_registrations_for_teaching_group(conn, gid)
    # المسجّلون من هذا القسم على مجموعات أخرى سيُنقلون (لا يزيدون العدد مرتين إن كانوا على الهدف)
    projected = enrolled + len(to_move)
    if capacity_max is not None and projected > capacity_max:
        raise ValueError(
            f"تجاوز السعة: المسجّلون={enrolled} + سيتم نقل {len(to_move)} "
            f"> السعة {capacity_max}"
        )

    conflicts = find_student_conflicts_for_group(
        conn,
        student_ids=to_move,
        teaching_group_id=gid,
        semester=sem,
        course_name=cname,
    )
    if conflicts and not allow_conflicts:
        raise ValueError(
            f"تعارض أوقات لـ {len({c['student_id'] for c in conflicts})} طالباً مع جدول القسم — "
            "راجع الأوقات أو أكّد مع allow_conflicts"
        )

    # مجموعات المصدر قبل النقل (للتدقيق والامتحانات)
    from_ids: list[int] = []
    if student_ids:
        placeholders = ",".join("?" for _ in student_ids)
        rows = cur.execute(
            f"""
            SELECT DISTINCT teaching_group_id FROM registrations
            WHERE lower(trim(course_name)) = lower(trim(?))
              AND student_id IN ({placeholders})
              AND teaching_group_id IS NOT NULL
            """,
            (cname, *student_ids),
        ).fetchall() or []
        from_ids = [int(_row_get(r, "teaching_group_id", 0, 0) or 0) for r in rows]

    moved = 0
    if to_move:
        placeholders = ",".join("?" for _ in to_move)
        cur.execute(
            f"""
            UPDATE registrations
            SET teaching_group_id = ?
            WHERE lower(trim(course_name)) = lower(trim(?))
              AND student_id IN ({placeholders})
            """,
            (gid, cname, *to_move),
        )
        moved = int(cur.rowcount or 0)

    from backend.database.database import is_postgresql

    actor_s = (actor or "").strip()
    if table_exists(conn, "department_general_group_bindings"):
        conflict_target = (
            "EXCLUDED" if is_postgresql() else "excluded"
        )
        cur.execute(
            f"""
            INSERT INTO department_general_group_bindings
                (semester, consumer_department_id, course_name, teaching_group_id, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (semester, consumer_department_id, course_name)
            DO UPDATE SET
                teaching_group_id = {conflict_target}.teaching_group_id,
                updated_by = {conflict_target}.updated_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (sem, dept, cname, gid, actor_s),
        )

    exam_note = _exams_note_for_migration(
        conn, course_name=cname, from_group_ids=from_ids, to_group_id=gid
    )
    details = (
        f"dept={dept}, course={cname}, semester={sem}, "
        f"to_group={gid}, moved={moved}, from={from_ids}, actor={actor_s}"
    )
    try:
        log_activity(action="select_general_group", details=details, actor=actor_s or None)
    except Exception:
        pass

    return {
        "status": "ok",
        "course_name": cname,
        "semester": sem,
        "teaching_group_id": gid,
        "group_code": str(_row_get(g, "group_code", 4, "") or ""),
        "moved_count": moved,
        "dept_registered_count": len(student_ids),
        "capacity_max": capacity_max,
        "enrolled_after": count_registrations_for_teaching_group(conn, gid),
        "conflicts_bypassed": len(conflicts) if allow_conflicts else 0,
        "exam_note": exam_note,
        "split_resolved": True,
    }


def expand_registration_options_with_general(
    conn,
    options: list[dict[str, Any]],
    *,
    course_name: str,
    semester: str | None,
    student_department_id: int,
) -> list[dict[str, Any]]:
    """إن كان المقرر اتجاه عام وقسم الطالب تخصصي: أضف مجموعات GENERAL."""
    cname = (course_name or "").strip()
    dept = int(student_department_id or 0)
    if not cname or dept <= 0:
        return options
    if not is_specialty_consumer_department(conn, dept):
        return options
    try:
        from backend.core.department_scope_policy import course_is_college_general

        if not course_is_college_general(conn, cname):
            return options
    except Exception:
        return options
    gen_id = _general_dept_id(conn)
    if not gen_id:
        return options
    sem = _normalize_semester(conn, semester)
    existing = {int(o.get("teaching_group_id") or o.get("id") or 0) for o in options}
    groups = list_teaching_groups(
        conn, semester=sem, department_id=int(gen_id), course_name=cname
    )
    # إن وُجد ربط صريح للقسم: أظهر المجموعة المربوطة أولاً، مع الإبقاء على الباقي للاختيار
    bindings = list_bindings(conn, semester=sem, consumer_department_id=dept)
    preferred = bindings.get(cname.lower())
    for g in groups:
        gid = int(g.get("id") or 0)
        if not gid or gid in existing:
            continue
        options.append(
            {
                **g,
                "teaching_group_id": gid,
                "enrolled_count": count_registrations_for_teaching_group(conn, gid),
                "is_college_general_group": True,
                "is_preferred_binding": bool(preferred and int(preferred) == gid),
            }
        )
        existing.add(gid)
    if preferred:
        options.sort(
            key=lambda o: (
                0 if int(o.get("teaching_group_id") or 0) == int(preferred) else 1,
                str(o.get("group_code") or ""),
            )
        )
    return options
