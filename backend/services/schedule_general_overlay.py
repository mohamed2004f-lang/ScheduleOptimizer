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
    has_sem = "semester" in reg_cols
    rows = cur.execute(
        f"""
        SELECT lower(trim(r.course_name)) AS cname,
               r.teaching_group_id AS gid,
               COUNT(DISTINCT r.student_id) AS cnt
               {", r.semester AS rsem" if has_sem else ""}
        FROM registrations r
        INNER JOIN students st ON st.student_id = r.student_id AND {active_stu}
        INNER JOIN teaching_groups tg ON tg.id = r.teaching_group_id AND tg.is_active = 1
        WHERE st.department_id = ?
          AND tg.department_id = ?
          AND r.teaching_group_id IS NOT NULL
        GROUP BY lower(trim(r.course_name)), r.teaching_group_id{(", r.semester" if has_sem else "")}
        """,
        (int(consumer_department_id), int(general_department_id)),
    ).fetchall() or []
    out: dict[str, dict[int, int]] = {}
    for r in rows:
        cname = str(_row_get(r, "cname", 0, "") or "").strip().lower()
        gid = int(_row_get(r, "gid", 1, 0) or 0)
        cnt = int(_row_get(r, "cnt", 2, 0) or 0)
        if not cname or gid <= 0 or cnt <= 0:
            continue
        if has_sem:
            rsem = str(_row_get(r, "rsem", 3, "") or "")
            if not _semester_matches_ops(conn, rsem, semester):
                continue
        bucket = out.setdefault(cname, {})
        bucket[gid] = int(bucket.get(gid, 0)) + cnt
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


def _schedule_row_dict(r, *, pk_col_hint: str = "section_id") -> dict[str, Any]:
    return {
        "section_id": int(_row_get(r, "section_id", 0, 0) or 0),
        "course_name": str(_row_get(r, "course_name", 1, "") or "").strip(),
        "day": str(_row_get(r, "day", 2, "") or ""),
        "time": str(_row_get(r, "time", 3, "") or ""),
        "room": str(_row_get(r, "room", 4, "") or ""),
        "instructor": str(_row_get(r, "instructor", 5, "") or ""),
        "semester": str(_row_get(r, "semester", 6, "") or ""),
        "instructor_id": _row_get(r, "instructor_id", 7),
        "teaching_group_id": int(_row_get(r, "teaching_group_id", 8, 0) or 0) or None,
        "department_id": int(_row_get(r, "department_id", 9, 0) or 0) or None,
        "group_code": str(_row_get(r, "group_code", 10, "—") or "—"),
        "tg_department_name": str(_row_get(r, "tg_department_name", 11, "") or ""),
        "tg_instructor_name": str(_row_get(r, "tg_instructor_name", 12, "") or ""),
    }


def _pick_single_section_rows(rows: list, *, semester: str, conn) -> list:
    """
    إن وُجدت أكثر من شعبة (teaching_group_id مختلف) لا تُعرض في شبكة القسم —
    تبقى للاختيار في اللوحة. شعبة واحدة فقط (أو صفوف بلا مجموعة واحدة) تُقبل.
    """
    term_rows = [
        r
        for r in rows
        if _semester_matches_ops(conn, str(_row_get(r, "semester", 6, "") or ""), semester)
    ]
    if not term_rows:
        return []
    buckets: dict[str, list] = {}
    for r in term_rows:
        gid = int(_row_get(r, "teaching_group_id", 8, 0) or 0)
        if gid > 0:
            key = f"tg:{gid}"
        else:
            # بلا مجموعة: اجمع حسب الأستاذ لتمييز الشعب غير المربوطة
            iid = _row_get(r, "instructor_id", 7)
            iname = str(_row_get(r, "instructor", 5, "") or "").strip()
            key = f"inst:{iid or iname or 'unknown'}"
        buckets.setdefault(key, []).append(r)
    if len(buckets) == 1:
        return next(iter(buckets.values()))
    return []  # متعدد → لا حقن تلقائي في الشبكة


def fetch_overlay_schedule_items(
    conn,
    *,
    consumer_department_id: int,
    semester: str | None = None,
    pk_col: str = "id",
) -> list[dict[str, Any]]:
    """
    صفوف overlay لشبكة القسم: فقط الشعبة التي عليها طلبة القسم / الربط الصريح.
    باقي شعب الاتجاه العام لا تُحقَن هنا (تظهر في لوحة الاختيار + جدول GENERAL الكامل).
    """
    if not is_specialty_consumer_department(conn, consumer_department_id):
        return []
    if not table_exists(conn, "schedule"):
        return []
    resolved = resolve_effective_general_groups(
        conn,
        consumer_department_id=int(consumer_department_id),
        semester=semester,
    )
    resolved = enrich_resolve_with_single_group_auto(
        conn, resolved, consumer_department_id=int(consumer_department_id)
    )
    by_course = resolved.get("by_course") or {}
    group_ids = sorted(
        {
            int(v["teaching_group_id"])
            for v in by_course.values()
            if int(v.get("teaching_group_id") or 0) > 0
        }
    )
    gen_id = int(resolved.get("general_department_id") or 0) or (_general_dept_id(conn) or 0)
    if not gen_id:
        return []
    sem = str(resolved.get("semester") or semester or "")
    reg_keys = _dept_registered_general_course_keys(
        conn, semester=sem, consumer_department_id=int(consumer_department_id)
    )
    course_keys = set(by_course.keys()) | set(reg_keys.keys())
    cur = conn.cursor()
    scols = {c.lower() for c in fetch_table_columns(conn, "schedule")}
    from backend.services import teaching_groups as tg_svc

    rows: list = []
    # 1) شعب مربوطة/محددة من تسجيلات طلبة القسم فقط
    if group_ids and "teaching_group_id" in scols and table_exists(conn, "teaching_groups"):
        placeholders = ",".join("?" for _ in group_ids)
        rows = list(
            cur.execute(
                f"""
                SELECT
                    s.{pk_col} AS section_id,
                    s.course_name, s.day, s.time, s.room, s.instructor, s.semester,
                    s.instructor_id, s.teaching_group_id, s.department_id,
                    COALESCE(tg.group_code, '—') AS group_code,
                    COALESCE(td.name_ar, td.code, '') AS tg_department_name,
                    COALESCE(ti.name, s.instructor, '') AS tg_instructor_name
                FROM schedule s
                INNER JOIN teaching_groups tg ON tg.id = s.teaching_group_id AND tg.is_active = 1
                LEFT JOIN departments td ON td.id = tg.department_id
                LEFT JOIN instructors ti ON ti.id = COALESCE(tg.instructor_id, s.instructor_id)
                WHERE s.teaching_group_id IN ({placeholders})
                ORDER BY s.{pk_col}
                """,
                tuple(group_ids),
            ).fetchall()
            or []
        )

    covered_keys = {
        str(_row_get(r, "course_name", 1, "") or "").strip().lower()
        for r in rows
        if str(_row_get(r, "course_name", 1, "") or "").strip()
    }
    # 2) احتياطي صارم: مقرر مسجّل بلا شعبة محددة → اعرض فقط إن وُجدت شعبة واحدة واضحة
    missing_keys = sorted(k for k in course_keys if k not in covered_keys)
    if missing_keys:
        placeholders = ",".join("?" for _ in missing_keys)
        extra_raw = cur.execute(
            f"""
            SELECT
                s.{pk_col} AS section_id,
                s.course_name, s.day, s.time, s.room, s.instructor, s.semester,
                s.instructor_id, s.teaching_group_id, s.department_id,
                COALESCE(tg.group_code, '—') AS group_code,
                COALESCE(td.name_ar, td.code, '') AS tg_department_name,
                COALESCE(ti.name, s.instructor, '') AS tg_instructor_name
            FROM schedule s
            LEFT JOIN teaching_groups tg ON tg.id = s.teaching_group_id AND tg.is_active = 1
            LEFT JOIN departments td ON td.id = COALESCE(tg.department_id, s.department_id)
            LEFT JOIN instructors ti ON ti.id = COALESCE(tg.instructor_id, s.instructor_id)
            WHERE lower(trim(s.course_name)) IN ({placeholders})
            ORDER BY CASE WHEN s.department_id = ? THEN 0 ELSE 1 END, s.{pk_col}
            """,
            tuple(missing_keys) + (gen_id,),
        ).fetchall() or []
        by_course_extra: dict[str, list] = {}
        for r in extra_raw:
            ck = str(_row_get(r, "course_name", 1, "") or "").strip().lower()
            if ck:
                by_course_extra.setdefault(ck, []).append(r)
        for ck, crow_list in by_course_extra.items():
            picked = _pick_single_section_rows(crow_list, semester=sem, conn=conn)
            rows.extend(picked)

    items: list[dict[str, Any]] = []
    for r in rows:
        cname = str(_row_get(r, "course_name", 1, "") or "").strip()
        if not cname:
            continue
        if not _semester_matches_ops(conn, str(_row_get(r, "semester", 6, "") or ""), sem):
            continue
        gid = int(_row_get(r, "teaching_group_id", 8, 0) or 0)
        meta = by_course.get(cname.lower()) or {}
        # شبكة القسم: فقط شعبة الربط/الأغلبية — لا كل شعب المقرر
        if meta and int(meta.get("teaching_group_id") or 0) > 0:
            if gid and int(meta.get("teaching_group_id") or 0) != gid:
                continue
        gcode = str(_row_get(r, "group_code", 10, "—") or "—")
        if gid:
            dept_count = count_dept_students_on_group(
                conn,
                teaching_group_id=gid,
                consumer_department_id=int(consumer_department_id),
            )
        else:
            dept_count = int(reg_keys.get(cname.lower()) or 0)
        items.append(
            {
                "section_id": int(_row_get(r, "section_id", 0, 0) or 0),
                "course_name": cname,
                "day": str(_row_get(r, "day", 2, "") or ""),
                "time": str(_row_get(r, "time", 3, "") or ""),
                "room": str(_row_get(r, "room", 4, "") or ""),
                "instructor": str(_row_get(r, "instructor", 5, "") or ""),
                "semester": str(_row_get(r, "semester", 6, "") or ""),
                "instructor_id": _row_get(r, "instructor_id", 7),
                "student_count": dept_count,
                "teaching_group_id": gid or None,
                "department_id": int(_row_get(r, "department_id", 9, gen_id) or gen_id),
                "group_code": gcode,
                "group_code_label": tg_svc.group_code_label(gcode),
                "teaching_group_label": tg_svc.format_teaching_group_label(
                    course_name=cname,
                    department_name=str(_row_get(r, "tg_department_name", 11, "") or ""),
                    group_code=gcode,
                    instructor_name=str(
                        _row_get(r, "tg_instructor_name", 12, "")
                        or _row_get(r, "instructor", 5, "")
                        or ""
                    ),
                ),
                "is_overlay_general": True,
                "is_college_general": True,
                "overlay_source": meta.get("source")
                or ("registrations" if cname.lower() in reg_keys else "single_section"),
            }
        )
    return items


def fetch_full_general_timetable(
    conn,
    *,
    semester: str | None = None,
    pk_col: str = "id",
) -> dict[str, Any]:
    """جدول الاتجاه العام بالكامل للفصل الحالي — عرض فقط لرؤساء الأقسام التخصصية.

    يُرجع نفس تخطيط أعمدة العرض (مجموعة 1 / مجموعة 2) الذي يراه رئيس الاتجاه العام.
    """
    from backend.services import schedule_display_tracks as sdt
    from backend.services import teaching_groups as tg_svc
    from backend.core.schedule_stage_layout import (
        enrich_schedule_row_stage_fields,
        load_course_codes_by_name,
    )

    sem = _normalize_semester(conn, semester)
    gen_id = _general_dept_id(conn)
    empty = {
        "semester": sem,
        "rows": [],
        "department_id": int(gen_id) if gen_id else None,
        "count": 0,
        "use_display_tracks": True,
        "display_tracks": sdt.default_track_defs(),
    }
    if not gen_id or not table_exists(conn, "schedule"):
        return empty
    cur = conn.cursor()
    has_tg = table_exists(conn, "teaching_groups")
    has_tg_display = bool(has_tg and sdt.teaching_groups_has_display_column(conn))
    tg_display_select = (
        "tg.display_column AS tg_display_column," if has_tg_display else "NULL AS tg_display_column,"
    )
    if has_tg:
        raw = cur.execute(
            f"""
            SELECT
                s.{pk_col} AS section_id,
                s.course_name, s.day, s.time, s.room, s.instructor, s.semester,
                s.instructor_id, s.teaching_group_id, s.department_id,
                COALESCE(tg.group_code, '—') AS group_code,
                COALESCE(td.name_ar, td.code, '') AS tg_department_name,
                COALESCE(ti.name, s.instructor, '') AS tg_instructor_name,
                {tg_display_select}
                tg.group_code AS tg_group_code
            FROM schedule s
            LEFT JOIN teaching_groups tg ON tg.id = s.teaching_group_id AND tg.is_active = 1
            LEFT JOIN departments td ON td.id = COALESCE(tg.department_id, s.department_id)
            LEFT JOIN instructors ti ON ti.id = COALESCE(tg.instructor_id, s.instructor_id)
            WHERE s.department_id = ?
            ORDER BY s.day, s.time, s.course_name
            """,
            (int(gen_id),),
        ).fetchall() or []
    else:
        raw = cur.execute(
            f"""
            SELECT
                s.{pk_col} AS section_id,
                s.course_name, s.day, s.time, s.room, s.instructor, s.semester,
                s.instructor_id, NULL AS teaching_group_id, s.department_id,
                '—' AS group_code, '' AS tg_department_name, s.instructor AS tg_instructor_name,
                NULL AS tg_display_column, NULL AS tg_group_code
            FROM schedule s
            WHERE s.department_id = ?
            ORDER BY s.day, s.time, s.course_name
            """,
            (int(gen_id),),
        ).fetchall() or []

    display_tracks = sdt.list_display_tracks(
        conn, semester=sem, department_id=int(gen_id), ensure_defaults=True
    )
    tracks_n = len(display_tracks) or sdt.DEFAULT_TRACK_COUNT

    rows: list[dict[str, Any]] = []
    for r in raw:
        if not _semester_matches_ops(conn, str(_row_get(r, "semester", 6, "") or ""), sem):
            continue
        gcode = str(_row_get(r, "group_code", 10, "—") or "—")
        cname = str(_row_get(r, "course_name", 1, "") or "").strip()
        tg_display = _row_get(r, "tg_display_column", 13, None)
        item = {
            "section_id": int(_row_get(r, "section_id", 0, 0) or 0),
            "course_name": cname,
            "day": str(_row_get(r, "day", 2, "") or ""),
            "time": str(_row_get(r, "time", 3, "") or ""),
            "room": str(_row_get(r, "room", 4, "") or ""),
            "instructor": str(_row_get(r, "instructor", 5, "") or ""),
            "semester": str(_row_get(r, "semester", 6, "") or ""),
            "instructor_id": _row_get(r, "instructor_id", 7),
            "student_count": 0,
            "teaching_group_id": int(_row_get(r, "teaching_group_id", 8, 0) or 0) or None,
            "department_id": int(gen_id),
            "group_code": gcode,
            "group_code_label": tg_svc.group_code_label(gcode),
            "tg_display_column": tg_display,
            "display_column": tg_display,
            "is_overlay_general": True,
            "is_college_general": True,
            "is_full_general_ref": True,
        }
        rows.append(item)
    try:
        code_map = load_course_codes_by_name(conn, [x["course_name"] for x in rows])
        for item in rows:
            enrich_schedule_row_stage_fields(conn, item, course_code_by_name=code_map)
            item["is_college_general"] = True
    except Exception:
        pass
    try:
        sdt.enrich_schedule_rows_display_columns(conn, rows, tracks_n=tracks_n)
    except Exception:
        logger.exception("full general timetable display_column enrich failed")
    return {
        "semester": sem,
        "department_id": int(gen_id),
        "rows": rows,
        "count": len(rows),
        "use_display_tracks": True,
        "display_tracks": display_tracks,
    }


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
    if not _is_overlay_candidate_course(conn, cname):
        return {
            "course_name": cname,
            "semester": sem,
            "options": [],
            "error": "المقرر ليس من الاتجاه العام",
        }
    groups = list_teaching_groups(
        conn, semester=sem, department_id=int(gen_id), course_name=cname
    )
    # بلا مجموعات: أنشئ/اربط مجموعة single من حصص الجدول (لا نُرجع teaching_group_id=0)
    if not groups and table_exists(conn, "schedule"):
        try:
            _ensure_general_single_group_from_schedule(
                conn, course_name=cname, semester=sem, general_department_id=int(gen_id)
            )
            groups = list_teaching_groups(
                conn, semester=sem, department_id=int(gen_id), course_name=cname
            )
        except Exception:
            logger.exception("ensure general single group for options failed")

    resolved = resolve_effective_general_groups(
        conn, consumer_department_id=int(consumer_department_id), semester=sem
    )
    current = (resolved.get("by_course") or {}).get(cname.lower())
    split_warning = None
    for w in resolved.get("split_warnings") or []:
        if str(w.get("course_name") or "").lower() == cname.lower():
            split_warning = w
            break

    # مسجّلو القسم في المقرر (حتى بلا teaching_group_id) — للعمود «مسجّلو قسمك»
    dept_on_course = len(
        _dept_students_registered_for_course(
            conn,
            course_name=cname,
            semester=sem,
            consumer_department_id=int(consumer_department_id),
        )
    )

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
        # إن لم تُربط الحصص بالمجموعة بعد — اعرض أوقات المقرر من الجدول
        if not slot_list:
            full = cur.execute(
                """
                SELECT day, time, room, semester FROM schedule
                WHERE lower(trim(course_name)) = lower(trim(?))
                  AND department_id = ?
                ORDER BY day, time
                """,
                (cname, int(gen_id)),
            ).fetchall() or []
            for s in full:
                if _semester_matches_ops(conn, str(_row_get(s, "semester", 3, "") or ""), sem):
                    slot_list.append(
                        {
                            "day": str(_row_get(s, "day", 0, "") or ""),
                            "time": str(_row_get(s, "time", 1, "") or ""),
                            "room": str(_row_get(s, "room", 2, "") or ""),
                        }
                    )
        cap_raw = g.get("capacity_max")
        try:
            cap_n = int(cap_raw) if cap_raw not in (None, "") else None
        except (TypeError, ValueError):
            cap_n = None
        if cap_n is not None and cap_n <= 0:
            cap_n = None  # 0 أو سالب = بلا حد (لا تُعرض كسعة صفر)
        enrolled = count_registrations_for_teaching_group(conn, gid)
        options.append(
            {
                "teaching_group_id": gid,
                "group_code": g.get("group_code"),
                "group_kind": g.get("group_kind"),
                "instructor_name": g.get("instructor_name") or g.get("instructor") or "",
                "capacity_max": cap_n,
                "enrolled_count": enrolled,
                "dept_enrolled_count": dept_on_course,
                "dept_on_group_count": count_dept_students_on_group(
                    conn,
                    teaching_group_id=gid,
                    consumer_department_id=int(consumer_department_id),
                ),
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


def _ensure_general_single_group_from_schedule(
    conn,
    *,
    course_name: str,
    semester: str,
    general_department_id: int,
) -> int | None:
    """إنشاء مجموعة single للاتجاه العام من حصص الجدول إن لم توجد مجموعات."""
    from backend.services import teaching_groups as tg_svc

    cname = (course_name or "").strip()
    sem = (semester or "").strip()
    gen_id = int(general_department_id or 0)
    if not cname or not sem or gen_id <= 0 or not table_exists(conn, "schedule"):
        return None
    cur = conn.cursor()
    pk_expr = tg_svc._schedule_section_pk_expr(conn, "s")
    rows = cur.execute(
        f"""
        SELECT {pk_expr} AS section_id, s.instructor_id, s.semester
        FROM schedule s
        WHERE lower(trim(s.course_name)) = lower(trim(?))
          AND s.department_id = ?
        ORDER BY 1
        """,
        (cname, gen_id),
    ).fetchall() or []
    section_ids: list[int] = []
    instructor_id = 0
    for r in rows:
        rsem = str(_row_get(r, "semester", 2, "") or "")
        if not _semester_matches_ops(conn, rsem, sem):
            continue
        sid = int(_row_get(r, "section_id", 0, 0) or 0)
        iid = int(_row_get(r, "instructor_id", 1, 0) or 0)
        if sid > 0:
            section_ids.append(sid)
        if iid > 0 and instructor_id <= 0:
            instructor_id = iid
    if not section_ids:
        return None
    if instructor_id <= 0:
        for sid in section_ids[:8]:
            gid = tg_svc.ensure_schedule_slot_teaching_group(conn, sid)
            if gid:
                return int(gid)
        return None
    saved = tg_svc.setup_course_offering(
        conn,
        course_name=cname,
        semester=sem,
        department_id=gen_id,
        group_kind=tg_svc.GROUP_KIND_SINGLE,
        groups=[{"instructor_id": instructor_id, "section_ids": section_ids}],
    )
    if saved:
        return int(saved[0].get("id") or 0) or None
    return None


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
    has_sem = "semester" in reg_cols
    rows = conn.cursor().execute(
        f"""
        SELECT DISTINCT r.student_id, {("r.semester" if has_sem else "''")} AS rsem
        FROM registrations r
        INNER JOIN students st ON st.student_id = r.student_id AND {active_stu}
        WHERE lower(trim(r.course_name)) = lower(trim(?))
          AND st.department_id = ?
        """,
        (cname, int(consumer_department_id)),
    ).fetchall() or []
    gen_id = _general_dept_id(conn) or 0
    sched_ok = _general_has_schedule_this_term(conn, cname, semester, int(gen_id))
    out_ids: list[str] = []
    for r in rows:
        sid = str(_row_get(r, "student_id", 0, "") or "").strip()
        if not sid:
            continue
        if has_sem:
            rsem = str(_row_get(r, "rsem", 1, "") or "")
            if not (_semester_matches_ops(conn, rsem, semester) or sched_ok):
                continue
        out_ids.append(sid)
    return out_ids


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
    try:
        capacity_max = int(cap_raw) if cap_raw not in (None, "") else None
    except (TypeError, ValueError):
        capacity_max = None
    if capacity_max is not None and capacity_max <= 0:
        capacity_max = None  # سعة 0 = غير محددة (لا تمنع الاختيار)
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
    try:
        acknowledge_general_course_times(
            conn,
            course_name=cname,
            semester=sem,
            consumer_department_id=dept,
            actor=actor_s,
        )
    except Exception:
        logger.exception("acknowledge after select failed")

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


# ---------------------------------------------------------------------------
# اكتشاف مبكر + تنبيه تغيّر الأوقات
# ---------------------------------------------------------------------------

def _seen_settings_key(semester: str, consumer_department_id: int) -> str:
    return f"gen_overlay_seen::{(semester or '').strip()}::dept:{int(consumer_department_id)}"


def _load_seen_map(conn, *, semester: str, consumer_department_id: int) -> dict[str, Any]:
    if not table_exists(conn, "app_settings"):
        return {}
    key = _seen_settings_key(semester, consumer_department_id)
    row = conn.cursor().execute(
        "SELECT value_json FROM app_settings WHERE key = ? LIMIT 1", (key,)
    ).fetchone()
    if not row:
        return {}
    raw = (row[0] if isinstance(row, (list, tuple)) else row["value_json"]) or ""
    try:
        import json

        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_seen_map(
    conn,
    *,
    semester: str,
    consumer_department_id: int,
    seen: dict[str, Any],
    actor: str | None = None,
) -> None:
    if not table_exists(conn, "app_settings"):
        return
    import json
    from datetime import datetime, timezone

    key = _seen_settings_key(semester, consumer_department_id)
    payload = json.dumps(seen, ensure_ascii=False)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    actor_s = (actor or "system").strip() or "system"
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO app_settings (key, value_json, updated_at, updated_by)
        VALUES (?,?,?,?)
        ON CONFLICT (key) DO UPDATE SET
            value_json = EXCLUDED.value_json,
            updated_at = EXCLUDED.updated_at,
            updated_by = EXCLUDED.updated_by
        """,
        (key, payload, now, actor_s),
    )


def slots_fingerprint_for_course(
    conn,
    *,
    course_name: str,
    semester: str,
    general_department_id: int | None = None,
) -> str:
    """بصمة أوقات كل مجموعات GENERAL للمقرر (للكشف عن التغيير)."""
    import hashlib

    cname = (course_name or "").strip()
    gen_id = int(general_department_id or 0) or (_general_dept_id(conn) or 0)
    if not cname or not gen_id or not table_exists(conn, "schedule"):
        return ""
    rows = conn.cursor().execute(
        """
        SELECT COALESCE(tg.group_code, ''), COALESCE(s.day, ''), COALESCE(s.time, ''),
               COALESCE(s.room, ''), COALESCE(s.teaching_group_id, 0)
        FROM schedule s
        INNER JOIN teaching_groups tg ON tg.id = s.teaching_group_id AND tg.is_active = 1
        WHERE tg.department_id = ?
          AND lower(trim(s.course_name)) = lower(trim(?))
          AND (COALESCE(TRIM(s.semester), '') = '' OR lower(trim(s.semester)) = lower(trim(?)))
        ORDER BY 1, 2, 3, 4, 5
        """,
        (int(gen_id), cname, semester),
    ).fetchall() or []
    parts = []
    for r in rows:
        parts.append(
            "|".join(
                str(_row_get(r, k, i, "") or "")
                for i, k in enumerate(
                    ("group_code", "day", "time", "room", "teaching_group_id")
                )
            )
        )
    blob = "\n".join(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24] if blob else "empty"


def acknowledge_general_course_times(
    conn,
    *,
    course_name: str,
    semester: str | None,
    consumer_department_id: int,
    actor: str | None = None,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    """يثبّت أن رئيس القسم اطّلع على أوقات المقرر الحالية."""
    cname = (course_name or "").strip()
    sem = _normalize_semester(conn, semester)
    dept = int(consumer_department_id or 0)
    if not cname or dept <= 0:
        raise ValueError("course_name و department مطلوبان")
    fp = fingerprint or slots_fingerprint_for_course(conn, course_name=cname, semester=sem)
    seen = _load_seen_map(conn, semester=sem, consumer_department_id=dept)
    from datetime import datetime, timezone

    seen[cname.lower()] = {
        "fingerprint": fp,
        "course_name": cname,
        "seen_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    _save_seen_map(conn, semester=sem, consumer_department_id=dept, seen=seen, actor=actor)
    return {"course_name": cname, "semester": sem, "fingerprint": fp, "acknowledged": True}


def _display_course_names_matching(
    conn, course_keys_lower: set[str]
) -> dict[str, str]:
    """lower → اسم العرض من courses أو أول تسجيل."""
    out: dict[str, str] = {}
    if not course_keys_lower:
        return out
    keys = sorted(course_keys_lower)
    if table_exists(conn, "courses"):
        placeholders = ",".join("?" for _ in keys)
        rows = conn.cursor().execute(
            f"""
            SELECT course_name FROM courses
            WHERE lower(trim(course_name)) IN ({placeholders})
            """,
            tuple(keys),
        ).fetchall() or []
        for r in rows:
            nm = str(_row_get(r, "course_name", 0, "") or "").strip()
            if nm:
                out[nm.lower()] = nm
    for k in keys:
        out.setdefault(k, k)
    return out


def _semester_matches_ops(conn, semester_value: str | None, ops_semester: str) -> bool:
    """مطابقة مرنة لتسمية الفصل (ops_label / aliases) مع قبول الفراغ."""
    raw = (semester_value or "").strip()
    if not raw:
        return True
    ops = (ops_semester or "").strip()
    if not ops:
        return True
    if raw.lower() == ops.lower():
        return True
    try:
        from backend.services.term_engine import (
            current_term_match_context,
            schedule_semester_matches_term_context,
        )

        ctx = current_term_match_context(conn)
        if ctx and schedule_semester_matches_term_context(raw, ctx):
            return True
    except Exception:
        pass
    return False


def _general_has_schedule_this_term(conn, course_name: str, semester: str, general_department_id: int) -> bool:
    """هل لمقرر اتجاه عام حصص مجدولة هذا الفصل (قسم GENERAL أو ملكية المقرر)؟"""
    if not table_exists(conn, "schedule"):
        return False
    cname = (course_name or "").strip()
    if not cname:
        return False
    rows = conn.cursor().execute(
        """
        SELECT semester, department_id FROM schedule
        WHERE lower(trim(course_name)) = lower(trim(?))
        """,
        (cname,),
    ).fetchall() or []
    gen_id = int(general_department_id or 0)
    for r in rows:
        rsem = str(_row_get(r, "semester", 0, "") or "")
        dept = int(_row_get(r, "department_id", 1, 0) or 0)
        if gen_id and dept and dept != gen_id:
            # اسمح أيضاً إن كان الصف على قسم آخر لكن المقرر اتجاه عام وله فصل مطابق
            pass
        if _semester_matches_ops(conn, rsem, semester):
            return True
    return False


def _is_overlay_candidate_course(conn, course_name: str) -> bool:
    """مقرر يستحق الظهور كـ overlay: اتجاه عام فقط — ليس مشترك الكلية."""
    cname = (course_name or "").strip()
    if not cname:
        return False
    try:
        from backend.core.department_scope_policy import (
            course_is_college_general,
            course_is_college_shared_catalog,
        )

        # المشترك يُدار من جدول القسم التخصصي — لا يُعرض في لوحة اختيار شعبة GENERAL
        if course_is_college_shared_catalog(conn, cname):
            return False
        if course_is_college_general(conn, cname):
            return True
    except Exception:
        pass
    # ملكية GENERAL أو رموز GS/GE — فقط إن لم تُصنَّف مشتركاً أعلاه
    try:
        gen_id = _general_dept_id(conn)
        if not gen_id or not table_exists(conn, "courses"):
            return False
        cols = {c.lower() for c in fetch_table_columns(conn, "courses")}
        if "owning_department_id" not in cols:
            return False
        row = conn.cursor().execute(
            """
            SELECT owning_department_id, COALESCE(course_code,'') FROM courses
            WHERE lower(trim(course_name)) = lower(trim(?)) LIMIT 1
            """,
            (cname,),
        ).fetchone()
        if not row:
            return False
        own = int(_row_get(row, "owning_department_id", 0, 0) or 0)
        code = str(_row_get(row, "course_code", 1, "") or "").strip().upper()
        if own == int(gen_id):
            return True
        if code.startswith("GS") or code.startswith("GE ") or code.startswith("GE"):
            return True
    except Exception:
        return False
    return False


def _dept_registered_general_course_keys(
    conn,
    *,
    semester: str,
    consumer_department_id: int,
) -> dict[str, int]:
    """course_lower → عدد طلبة القسم المسجّلين (حتى بلا teaching_group).

    ملاحظة: تسجيلات قديمة قد تحمل semester خاطئ (مثل 2023/2024) بينما الجدول الحالي 2026/2027.
    لذلك نُبقي المقرر إن طابق فصل التسجيل *أو* وُجدت له حصص GENERAL في الفصل الحالي.
    """
    if not table_exists(conn, "registrations") or not table_exists(conn, "students"):
        return {}
    from backend.core.enrollment_status_policy import operational_status_sql

    active_stu = operational_status_sql("st")
    reg_cols = {c.lower() for c in fetch_table_columns(conn, "registrations")}
    stu_cols = {c.lower() for c in fetch_table_columns(conn, "students")}
    if "department_id" not in stu_cols:
        return {}
    has_sem = "semester" in reg_cols
    gen_id = _general_dept_id(conn) or 0
    rows = conn.cursor().execute(
        f"""
        SELECT lower(trim(r.course_name)) AS cname,
               COUNT(DISTINCT r.student_id) AS cnt
               {", r.semester AS rsem" if has_sem else ""}
        FROM registrations r
        INNER JOIN students st ON st.student_id = r.student_id AND {active_stu}
        WHERE st.department_id = ?
        GROUP BY lower(trim(r.course_name)){(", r.semester" if has_sem else "")}
        """,
        (int(consumer_department_id),),
    ).fetchall() or []
    out: dict[str, int] = {}
    for r in rows:
        cname = str(_row_get(r, "cname", 0, "") or "").strip().lower()
        cnt = int(_row_get(r, "cnt", 1, 0) or 0)
        if not cname or cnt <= 0:
            continue
        if not _is_overlay_candidate_course(conn, cname):
            continue
        include = True
        if has_sem:
            rsem = str(_row_get(r, "rsem", 2, "") or "")
            sem_ok = _semester_matches_ops(conn, rsem, semester)
            # تسجيل بفصل قديم + جدول GENERAL للفصل الحالي → ما زال ذا صلة
            sched_ok = _general_has_schedule_this_term(conn, cname, semester, int(gen_id))
            include = bool(sem_ok or sched_ok)
        if not include:
            continue
        out[cname] = out.get(cname, 0) + cnt
    return out


def _dept_planned_general_course_keys(
    conn,
    *,
    semester: str,
    consumer_department_id: int,
) -> dict[str, int]:
    """مقررات GENERAL في خطط تسجيل مفتوحة/معتمدة لطلبة القسم."""
    if not table_exists(conn, "enrollment_plans") or not table_exists(conn, "enrollment_plan_items"):
        return {}
    if not table_exists(conn, "students"):
        return {}
    from backend.core.enrollment_status_policy import operational_status_sql
    from backend.core.department_scope_policy import course_is_college_general

    active_stu = operational_status_sql("st")
    stu_cols = {c.lower() for c in fetch_table_columns(conn, "students")}
    if "department_id" not in stu_cols:
        return {}
    plan_cols = {c.lower() for c in fetch_table_columns(conn, "enrollment_plans")}
    status_filter = ""
    if "status" in plan_cols:
        status_filter = " AND lower(COALESCE(ep.status, '')) IN ('draft','submitted','approved','open','pending') "
    sem_filter = ""
    params: list[Any] = [int(consumer_department_id)]
    if "semester" in plan_cols:
        sem_filter = " AND (COALESCE(TRIM(ep.semester), '') = '' OR lower(trim(ep.semester)) = lower(trim(?))) "
        params.append(semester)
    rows = conn.cursor().execute(
        f"""
        SELECT lower(trim(epi.course_name)) AS cname, COUNT(DISTINCT ep.student_id) AS cnt
        FROM enrollment_plan_items epi
        INNER JOIN enrollment_plans ep ON ep.id = epi.plan_id
        INNER JOIN students st ON st.student_id = ep.student_id AND {active_stu}
        WHERE st.department_id = ?
          {sem_filter}
          {status_filter}
        GROUP BY lower(trim(epi.course_name))
        """,
        tuple(params),
    ).fetchall() or []
    out: dict[str, int] = {}
    for r in rows:
        cname = str(_row_get(r, "cname", 0, "") or "").strip().lower()
        cnt = int(_row_get(r, "cnt", 1, 0) or 0)
        if not cname or cnt <= 0:
            continue
        try:
            if course_is_college_general(conn, cname):
                out[cname] = cnt
        except Exception:
            continue
    return out


def discover_general_courses_for_department(
    conn,
    *,
    consumer_department_id: int,
    semester: str | None = None,
) -> dict[str, Any]:
    """
    اكتشاف مبكر: مقررات الاتجاه العام المرتبطة بطلبة القسم (تسجيلات أو خطط)
    مع مجموعاتها وأوقاتها وحالة الربط وتنبيه تغيّر الأوقات.
    """
    dept = int(consumer_department_id or 0)
    sem = _normalize_semester(conn, semester)
    gen_id = _general_dept_id(conn)
    if not dept or not gen_id or not is_specialty_consumer_department(conn, dept):
        return {
            "semester": sem,
            "applicable": False,
            "courses": [],
            "times_changed_count": 0,
            "needs_choice_count": 0,
        }

    resolved = resolve_effective_general_groups(
        conn, consumer_department_id=dept, semester=sem
    )
    reg_keys = _dept_registered_general_course_keys(
        conn, semester=sem, consumer_department_id=dept
    )
    plan_keys = _dept_planned_general_course_keys(
        conn, semester=sem, consumer_department_id=dept
    )
    # مقررات لها مجموعات GENERAL في الفصل (حتى قبل تسجيل — لا؛ فقط المرتبطة بطلبة/خطط/ربط)
    all_keys = set(reg_keys) | set(plan_keys) | set((resolved.get("by_course") or {}).keys())
    # أيضاً مقررات مربوطة صراحة
    all_keys |= set((resolved.get("bindings") or {}).keys())

    # مقررات GENERAL التي لها مجموعات هذا الفصل وطلاّب القسم مسجّلون بالاسم
    # (مغطى عبر reg_keys بعد course_is_college_general)

    display = _display_course_names_matching(conn, all_keys)
    seen = _load_seen_map(conn, semester=sem, consumer_department_id=dept)
    split_by = {
        str(w.get("course_name") or "").lower(): w
        for w in (resolved.get("split_warnings") or [])
    }

    courses: list[dict[str, Any]] = []
    times_changed_count = 0
    needs_choice_count = 0
    for key in sorted(all_keys):
        cname = display.get(key) or key
        opts_payload = list_general_group_options(
            conn,
            course_name=cname,
            semester=sem,
            consumer_department_id=dept,
        )
        options = opts_payload.get("options") or []
        # ملخص أوقات مختصر لكل المجموعات
        slots_preview = []
        for o in options:
            for s in o.get("slots") or []:
                slots_preview.append(
                    {
                        "group_code": o.get("group_code"),
                        "day": s.get("day"),
                        "time": s.get("time"),
                        "room": s.get("room"),
                    }
                )
        fp = slots_fingerprint_for_course(
            conn, course_name=cname, semester=sem, general_department_id=int(gen_id)
        )
        prev = seen.get(key) if isinstance(seen.get(key), dict) else None
        prev_fp = str((prev or {}).get("fingerprint") or "")
        # أول ظهور: لا تنبيه تغيّر إن لم يُشاهد من قبل وكان fingerprint empty نسبياً —
        # ننبّه عند وجود مشاهدة سابقة وبصمة مختلفة، أو عند وجود أوقات ولم تُشاهد بعد ووُجد ربط/overlay
        times_changed = bool(prev_fp and fp and prev_fp != fp)
        never_seen = not prev_fp and bool(fp) and fp != "empty"
        meta = (resolved.get("by_course") or {}).get(key) or {}
        has_binding = key in (resolved.get("bindings") or {})
        needs_choice = bool(split_by.get(key)) or (
            len(options) > 1 and not has_binding and not meta.get("teaching_group_id")
        )
        if len(options) > 1 and not has_binding and meta.get("source") == "registrations":
            # أغلبية موجودة لكن انقسام أو لم يُثبَّت ربط
            if split_by.get(key):
                needs_choice = True
        if times_changed:
            times_changed_count += 1
        if needs_choice:
            needs_choice_count += 1
        in_schedule = bool(slots_preview) or (
            bool(meta.get("teaching_group_id")) and bool(options)
        )
        sources = []
        if key in reg_keys:
            sources.append("registrations")
        if key in plan_keys:
            sources.append("enrollment_plans")
        if has_binding:
            sources.append("binding")
        courses.append(
            {
                "course_name": cname,
                "course_key": key,
                "dept_registered_count": int(reg_keys.get(key) or 0),
                "dept_planned_count": int(plan_keys.get(key) or 0),
                "sources": sources,
                "groups_count": len(options),
                "options": options,
                "slots_preview": slots_preview,
                "current_teaching_group_id": opts_payload.get("current_teaching_group_id"),
                "binding_source": meta.get("source"),
                "has_binding": has_binding,
                "in_schedule_overlay": in_schedule,
                "needs_choice": needs_choice,
                "split_warning": split_by.get(key),
                "fingerprint": fp,
                "times_changed": times_changed,
                "never_seen": never_seen and not times_changed,
                "attention": times_changed or needs_choice or (never_seen and not in_schedule),
            }
        )

    courses.sort(
        key=lambda c: (
            0 if c.get("times_changed") else 1,
            0 if c.get("needs_choice") else 1,
            0 if c.get("attention") else 1,
            str(c.get("course_name") or ""),
        )
    )
    return {
        "semester": sem,
        "applicable": True,
        "department_id": dept,
        "courses": courses,
        "times_changed_count": times_changed_count,
        "needs_choice_count": needs_choice_count,
        "split_warnings": resolved.get("split_warnings") or [],
        "by_course": resolved.get("by_course") or {},
    }


def enrich_resolve_with_single_group_auto(
    conn,
    resolved: dict[str, Any],
    *,
    consumer_department_id: int,
) -> dict[str, Any]:
    """
    إن وُجدت تسجيلات لمقرر GENERAL بلا مجموعة، ومجموعة GENERAL واحدة فقط —
    اعتبرها فعّالة للعرض (بدون كتابة ربط).
    """
    sem = str(resolved.get("semester") or "")
    gen_id = int(resolved.get("general_department_id") or 0) or (_general_dept_id(conn) or 0)
    if not gen_id:
        return resolved
    reg_keys = _dept_registered_general_course_keys(
        conn, semester=sem, consumer_department_id=int(consumer_department_id)
    )
    by_course = dict(resolved.get("by_course") or {})
    for key, cnt in reg_keys.items():
        if key in by_course:
            continue
        groups = list_teaching_groups(
            conn, semester=sem, department_id=int(gen_id), course_name=key
        )
        if len(groups) != 1:
            continue
        gid = int(groups[0].get("id") or 0)
        if gid <= 0:
            continue
        by_course[key] = {
            "course_name": key,
            "teaching_group_id": gid,
            "source": "auto_single",
            "dept_enrolled": int(cnt),
            "group_counts": {str(gid): int(cnt)},
        }
    resolved = dict(resolved)
    resolved["by_course"] = by_course
    return resolved
