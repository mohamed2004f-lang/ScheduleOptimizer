"""مجموعات التدريس — فصل مجموعة الطلاب (A/B) عن حصص الجدول (محاضرات)."""

from __future__ import annotations

import datetime
from typing import Any

from backend.core.faculty_axes import normalize_instructor_name
from backend.database.database import fetch_table_columns, schedule_pk_column, table_exists
from backend.services.utilities import get_current_term, schedule_semester_matches_current_term

GROUP_KIND_SINGLE = "single"
GROUP_KIND_SPLIT = "split"
DEFAULT_GROUP_CODE = "—"
VALID_GROUP_KINDS = frozenset({GROUP_KIND_SINGLE, GROUP_KIND_SPLIT})


def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat(timespec="seconds")


def _schedule_section_pk_expr(conn, alias: str = "s") -> str:
    """معرّف حصة الجدول — SQLite قد يترك id فارغاً ويستخدم rowid."""
    pk = schedule_pk_column(conn)
    if pk == "id":
        return f"COALESCE({alias}.id, {alias}.rowid)"
    return f"{alias}.{pk}"


def _schedule_section_pk_expr_bare(conn) -> str:
    pk = schedule_pk_column(conn)
    if pk == "id":
        return "COALESCE(id, rowid)"
    return pk


def _row_val(row, idx: int = 0, key: str | None = None):
    if row is None:
        return None
    if key and hasattr(row, "keys"):
        try:
            return row[key]
        except (KeyError, TypeError):
            pass
    try:
        return row[idx]
    except (IndexError, TypeError):
        return None


def normalize_group_code(code: str | None) -> str:
    raw = (code or "").strip()
    if not raw or raw in ("-", "—", "–"):
        return DEFAULT_GROUP_CODE
    return raw.upper()


def group_code_label(code: str | None) -> str:
    c = normalize_group_code(code)
    if c == DEFAULT_GROUP_CODE:
        return "الكل"
    return c


def format_teaching_group_label(
    *,
    course_name: str,
    department_name: str = "",
    group_code: str = DEFAULT_GROUP_CODE,
    instructor_name: str = "",
) -> str:
    parts = [(course_name or "").strip()]
    if (department_name or "").strip():
        parts.append(department_name.strip())
    gc = group_code_label(group_code)
    if gc != "الكل":
        parts.append(f"مجموعة {gc}")
    if (instructor_name or "").strip() and instructor_name.strip() != "—":
        parts.append(instructor_name.strip())
    return " — ".join(p for p in parts if p)


def _instructor_name_map(cur) -> dict[str, int]:
    out: dict[str, int] = {}
    if not table_exists(cur.connection, "instructors"):
        return out
    for row in cur.execute("SELECT id, COALESCE(name, '') FROM instructors").fetchall():
        iid = int(_row_val(row, 0) or 0)
        name = (_row_val(row, 1) or "").strip()
        norm = normalize_instructor_name(name)
        if iid and norm and norm not in out:
            out[norm] = iid
    return out


def _resolve_instructor_id(instructor_id: int, instructor_name: str, name_map: dict[str, int]) -> int:
    if int(instructor_id or 0) > 0:
        return int(instructor_id)
    norm = normalize_instructor_name(instructor_name)
    return int(name_map.get(norm) or 0)


def _resolve_department_id_for_schedule_row(
    conn,
    cur,
    *,
    course_name: str,
    schedule_department_id: int | None,
) -> int:
    if schedule_department_id is not None and int(schedule_department_id) > 0:
        return int(schedule_department_id)
    if table_exists(conn, "courses"):
        row = cur.execute(
            """
            SELECT owning_department_id FROM courses
            WHERE lower(trim(course_name)) = lower(trim(?))
            LIMIT 1
            """,
            ((course_name or "").strip(),),
        ).fetchone()
        oid = int(_row_val(row, 0) or 0)
        if oid > 0:
            return oid
    return 0


def _group_row_to_dict(row) -> dict[str, Any]:
    if hasattr(row, "keys"):
        d = dict(row)
    else:
        d = {
            "id": row[0],
            "course_name": row[1],
            "semester": row[2],
            "department_id": row[3],
            "group_code": row[4],
            "group_kind": row[5],
            "instructor_id": row[6],
            "capacity_max": row[7],
            "program_course_id": row[8],
            "note": row[9],
            "is_active": row[10],
            "department_name": row[11] if len(row) > 11 else "",
            "instructor_name": row[12] if len(row) > 12 else "",
        }
    d["group_code_label"] = group_code_label(d.get("group_code"))
    d["display_label"] = format_teaching_group_label(
        course_name=str(d.get("course_name") or ""),
        department_name=str(d.get("department_name") or ""),
        group_code=str(d.get("group_code") or DEFAULT_GROUP_CODE),
        instructor_name=str(d.get("instructor_name") or ""),
    )
    return d


def _groups_base_sql() -> str:
    return """
        SELECT tg.id, tg.course_name, tg.semester, tg.department_id,
               tg.group_code, tg.group_kind, tg.instructor_id,
               tg.capacity_max, tg.program_course_id, tg.note, tg.is_active,
               COALESCE(d.name_ar, d.code, '') AS department_name,
               COALESCE(i.name, '') AS instructor_name
        FROM teaching_groups tg
        LEFT JOIN departments d ON d.id = tg.department_id
        LEFT JOIN instructors i ON i.id = tg.instructor_id
    """


def list_teaching_groups(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
    course_name: str | None = None,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    if not table_exists(conn, "teaching_groups"):
        return []
    sem = (semester or "").strip()
    if not sem:
        tname, tyear = get_current_term(conn=conn)
        sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
    cur = conn.cursor()
    sql = _groups_base_sql() + " WHERE tg.semester = ?"
    params: list[Any] = [sem]
    if active_only:
        sql += " AND tg.is_active = 1"
    if department_id is not None:
        sql += " AND tg.department_id = ?"
        params.append(int(department_id))
    if course_name:
        sql += " AND lower(trim(tg.course_name)) = lower(trim(?))"
        params.append((course_name or "").strip())
    sql += " ORDER BY tg.course_name, tg.department_id, tg.group_code"
    rows = cur.execute(sql, tuple(params)).fetchall()
    return [_group_row_to_dict(r) for r in rows]


def get_teaching_group(conn, group_id: int) -> dict[str, Any] | None:
    if not table_exists(conn, "teaching_groups"):
        return None
    cur = conn.cursor()
    row = cur.execute(
        _groups_base_sql() + " WHERE tg.id = ?",
        (int(group_id),),
    ).fetchone()
    if not row:
        return None
    g = _group_row_to_dict(row)
    g["section_ids"] = list_linked_section_ids(conn, int(group_id))
    return g


def list_linked_section_ids(conn, teaching_group_id: int) -> list[int]:
    if not table_exists(conn, "schedule"):
        return []
    sid_expr = _schedule_section_pk_expr_bare(conn)
    cur = conn.cursor()
    cols = {c.lower() for c in fetch_table_columns(conn, "schedule")}
    if "teaching_group_id" not in cols:
        return []
    rows = cur.execute(
        f"""
        SELECT DISTINCT {sid_expr} FROM schedule
        WHERE teaching_group_id = ?
        ORDER BY {sid_expr}
        """,
        (int(teaching_group_id),),
    ).fetchall()
    out: list[int] = []
    for r in rows:
        sid = int(_row_val(r, 0) or 0)
        if sid:
            out.append(sid)
    return out


def create_teaching_group(
    conn,
    *,
    course_name: str,
    semester: str,
    department_id: int,
    instructor_id: int,
    group_code: str = DEFAULT_GROUP_CODE,
    group_kind: str = GROUP_KIND_SINGLE,
    capacity_max: int | None = None,
    program_course_id: int | None = None,
    note: str = "",
) -> dict[str, Any]:
    cname = (course_name or "").strip()
    sem = (semester or "").strip()
    dept = int(department_id)
    iid = int(instructor_id)
    if not cname or not sem or dept <= 0 or iid <= 0:
        raise ValueError("course_name, semester, department_id, instructor_id مطلوبة")
    gkind = (group_kind or GROUP_KIND_SINGLE).strip().lower()
    if gkind not in VALID_GROUP_KINDS:
        raise ValueError("group_kind غير صالح")
    gcode = normalize_group_code(group_code)
    if gkind == GROUP_KIND_SINGLE:
        gcode = DEFAULT_GROUP_CODE
    cur = conn.cursor()
    now = _now_iso()
    cur.execute(
        """
        INSERT INTO teaching_groups (
            course_name, semester, department_id, group_code, group_kind,
            instructor_id, capacity_max, program_course_id, note,
            is_active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            cname,
            sem,
            dept,
            gcode,
            gkind,
            iid,
            capacity_max,
            program_course_id,
            (note or "").strip(),
            now,
            now,
        ),
    )
    conn.commit()
    gid = int(cur.lastrowid or 0)
    if not gid:
        row = cur.execute(
            """
            SELECT id FROM teaching_groups
            WHERE course_name = ? AND semester = ? AND department_id = ? AND group_code = ?
            """,
            (cname, sem, dept, gcode),
        ).fetchone()
        gid = int(_row_val(row, 0) or 0)
    return get_teaching_group(conn, gid) or {}


def update_teaching_group(
    conn,
    group_id: int,
    *,
    instructor_id: int | None = None,
    group_kind: str | None = None,
    capacity_max: int | None = None,
    note: str | None = None,
    is_active: int | None = None,
) -> dict[str, Any] | None:
    cur = conn.cursor()
    sets: list[str] = ["updated_at = ?"]
    params: list[Any] = [_now_iso()]
    if instructor_id is not None:
        sets.append("instructor_id = ?")
        params.append(int(instructor_id))
    if group_kind is not None:
        gk = (group_kind or "").strip().lower()
        if gk not in VALID_GROUP_KINDS:
            raise ValueError("group_kind غير صالح")
        sets.append("group_kind = ?")
        params.append(gk)
    if capacity_max is not None:
        sets.append("capacity_max = ?")
        params.append(int(capacity_max) if capacity_max else None)
    if note is not None:
        sets.append("note = ?")
        params.append((note or "").strip())
    if is_active is not None:
        sets.append("is_active = ?")
        params.append(1 if int(is_active) else 0)
    params.append(int(group_id))
    cur.execute(
        f"UPDATE teaching_groups SET {', '.join(sets)} WHERE id = ?",
        tuple(params),
    )
    conn.commit()
    return get_teaching_group(conn, int(group_id))


def link_schedule_slots(conn, teaching_group_id: int, section_ids: list[int]) -> int:
    """يربط حصص الجدول بمجموعة تدريس؛ يزيل الربط السابق لهذه الحصص من مجموعات أخرى."""
    if not section_ids:
        return 0
    sid_where = _schedule_section_pk_expr_bare(conn)
    cur = conn.cursor()
    cols = {c.lower() for c in fetch_table_columns(conn, "schedule")}
    if "teaching_group_id" not in cols:
        raise RuntimeError("عمود teaching_group_id غير موجود في schedule")
    tg = get_teaching_group(conn, int(teaching_group_id))
    if not tg:
        raise ValueError("مجموعة التدريس غير موجودة")
    linked = 0
    for sid in section_ids:
        sid = int(sid)
        if sid <= 0:
            continue
        cur.execute(
            f"UPDATE schedule SET teaching_group_id = NULL WHERE {sid_where} = ?",
            (sid,),
        )
        cur.execute(
            f"UPDATE schedule SET teaching_group_id = ? WHERE {sid_where} = ?",
            (int(teaching_group_id), sid),
        )
        linked += 1
    conn.commit()
    return linked


def _fetch_schedule_slots_for_semester(
    conn,
    semester: str,
    *,
    department_id: int | None = None,
) -> list[dict[str, Any]]:
    if not table_exists(conn, "schedule"):
        return []
    sid_expr = _schedule_section_pk_expr(conn, "s")
    cur = conn.cursor()
    name_map = _instructor_name_map(cur)
    dept_sql = ""
    params: list[Any] = []
    if department_id is not None:
        dept_sql = " AND s.department_id = ? "
        params.append(int(department_id))
    rows = cur.execute(
        f"""
        SELECT {sid_expr} AS section_id,
               COALESCE(s.course_name, '') AS course_name,
               COALESCE(s.day, '') AS day,
               COALESCE(s.time, '') AS time,
               COALESCE(s.room, '') AS room,
               COALESCE(s.instructor, '') AS instructor,
               COALESCE(s.instructor_id, 0) AS instructor_id,
               COALESCE(s.semester, '') AS semester,
               s.department_id,
               s.teaching_group_id
        FROM schedule s
        WHERE COALESCE(TRIM(s.course_name), '') <> '' {dept_sql}
        ORDER BY s.course_name, {sid_expr}
        """,
        tuple(params),
    ).fetchall()
    out: list[dict[str, Any]] = []
    sem = (semester or "").strip()
    for row in rows:
        if hasattr(row, "keys"):
            d = dict(row)
        else:
            d = {
                "section_id": row[0],
                "course_name": row[1],
                "day": row[2],
                "time": row[3],
                "room": row[4],
                "instructor": row[5],
                "instructor_id": row[6],
                "semester": row[7],
                "department_id": row[8],
                "teaching_group_id": row[9],
            }
        sch_sem = (d.get("semester") or "").strip()
        if sem and sch_sem and not schedule_semester_matches_current_term(sch_sem, sem):
            continue
        sid = int(d.get("section_id") or 0)
        if not sid:
            continue
        cname = (d.get("course_name") or "").strip()
        dept_id = _resolve_department_id_for_schedule_row(
            conn,
            cur,
            course_name=cname,
            schedule_department_id=d.get("department_id"),
        )
        iid = _resolve_instructor_id(
            int(d.get("instructor_id") or 0),
            str(d.get("instructor") or ""),
            name_map,
        )
        out.append(
            {
                **d,
                "section_id": sid,
                "course_name": cname,
                "department_id": dept_id,
                "instructor_id": iid,
                "slot_label": f"{d.get('day') or ''} {d.get('time') or ''}".strip(),
            }
        )
    return out


def list_course_offerings_for_setup(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
) -> list[dict[str, Any]]:
    """مقررات الفصل مع حصص الجدول والمجموعات الحالية — لشاشة الإعداد."""
    sem = (semester or "").strip()
    if not sem:
        tname, tyear = get_current_term(conn=conn)
        sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
    slots = _fetch_schedule_slots_for_semester(conn, sem, department_id=department_id)
    groups = list_teaching_groups(conn, semester=sem, department_id=department_id, active_only=True)
    groups_by_id = {int(g["id"]): g for g in groups if g.get("id")}

    by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for slot in slots:
        cname = slot["course_name"]
        dept = int(slot.get("department_id") or 0)
        if not cname or dept <= 0:
            continue
        key = (cname.lower(), dept)
        bucket = by_key.get(key)
        if not bucket:
            dept_name = ""
            if table_exists(conn, "departments"):
                dr = conn.cursor().execute(
                    "SELECT COALESCE(name_ar, code, '') FROM departments WHERE id = ?",
                    (dept,),
                ).fetchone()
                dept_name = (_row_val(dr, 0) or "").strip()
            bucket = {
                "course_name": cname,
                "department_id": dept,
                "department_name": dept_name,
                "semester": sem,
                "slots": [],
                "groups": [],
                "group_kind": GROUP_KIND_SINGLE,
            }
            by_key[key] = bucket
        bucket["slots"].append(slot)

    for g in groups:
        key = ((g.get("course_name") or "").strip().lower(), int(g.get("department_id") or 0))
        bucket = by_key.get(key)
        if bucket:
            bucket["groups"].append({**g, "section_ids": list_linked_section_ids(conn, int(g["id"]))})
            bucket["group_kind"] = g.get("group_kind") or GROUP_KIND_SINGLE

    offerings = list(by_key.values())
    for off in offerings:
        if not off["groups"]:
            off["group_kind"] = GROUP_KIND_SINGLE
        off["needs_setup"] = any(int(s.get("department_id") or 0) <= 0 for s in off["slots"]) or any(
            int(s.get("instructor_id") or 0) <= 0 for s in off["slots"]
        )
        off["unlinked_slots"] = [
            s for s in off["slots"] if not s.get("teaching_group_id")
        ]
    offerings.sort(key=lambda x: (x.get("course_name") or ""))
    return offerings


def setup_course_offering(
    conn,
    *,
    course_name: str,
    semester: str,
    department_id: int,
    group_kind: str,
    groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    حفظ إعداد مقرر: single (مجموعة واحدة) أو split (A/B/C).
    groups: [{group_code, instructor_id, section_ids, capacity_max?, note?}]
    """
    cname = (course_name or "").strip()
    sem = (semester or "").strip()
    dept = int(department_id)
    gkind = (group_kind or GROUP_KIND_SINGLE).strip().lower()
    if not cname or not sem or dept <= 0:
        raise ValueError("course_name, semester, department_id مطلوبة")
    if gkind not in VALID_GROUP_KINDS:
        raise ValueError("group_kind غير صالح")
    if not groups:
        raise ValueError("groups مطلوبة")

    cur = conn.cursor()
    cur.execute(
        """
        UPDATE teaching_groups SET is_active = 0, updated_at = ?
        WHERE lower(trim(course_name)) = lower(trim(?))
          AND semester = ? AND department_id = ?
        """,
        (_now_iso(), cname, sem, dept),
    )

    saved: list[dict[str, Any]] = []
    if gkind == GROUP_KIND_SINGLE:
        g0 = groups[0]
        iid = int(g0.get("instructor_id") or 0)
        if iid <= 0:
            raise ValueError("instructor_id مطلوب")
        all_sections = []
        for g in groups:
            all_sections.extend(int(x) for x in (g.get("section_ids") or []) if int(x) > 0)
        if not all_sections:
            slots = _fetch_schedule_slots_for_semester(conn, sem, department_id=dept)
            all_sections = [
                int(s["section_id"])
                for s in slots
                if s["course_name"].lower() == cname.lower() and int(s.get("instructor_id") or 0) == iid
            ]
        rec = create_teaching_group(
            conn,
            course_name=cname,
            semester=sem,
            department_id=dept,
            instructor_id=iid,
            group_code=DEFAULT_GROUP_CODE,
            group_kind=GROUP_KIND_SINGLE,
            capacity_max=g0.get("capacity_max"),
            note=str(g0.get("note") or ""),
        )
        link_schedule_slots(conn, int(rec["id"]), list(dict.fromkeys(all_sections)))
        saved.append(get_teaching_group(conn, int(rec["id"])) or rec)
    else:
        for g in groups:
            gcode = normalize_group_code(str(g.get("group_code") or ""))
            if gcode == DEFAULT_GROUP_CODE:
                raise ValueError("رمز المجموعة مطلوب في وضع split")
            iid = int(g.get("instructor_id") or 0)
            if iid <= 0:
                raise ValueError(f"instructor_id مطلوب للمجموعة {gcode}")
            section_ids = [int(x) for x in (g.get("section_ids") or []) if int(x) > 0]
            rec = create_teaching_group(
                conn,
                course_name=cname,
                semester=sem,
                department_id=dept,
                instructor_id=iid,
                group_code=gcode,
                group_kind=GROUP_KIND_SPLIT,
                capacity_max=g.get("capacity_max"),
                note=str(g.get("note") or ""),
            )
            if section_ids:
                link_schedule_slots(conn, int(rec["id"]), section_ids)
            saved.append(get_teaching_group(conn, int(rec["id"])) or rec)

    conn.commit()
    return saved


def backfill_teaching_groups_for_semester(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
) -> dict[str, int]:
    """إنشاء مجموعات single افتراضية وربط حصص الجدول غير المربوطة."""
    sem = (semester or "").strip()
    if not sem:
        tname, tyear = get_current_term(conn=conn)
        sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
    if not table_exists(conn, "teaching_groups"):
        return {"created": 0, "linked": 0, "skipped": 0}

    slots = _fetch_schedule_slots_for_semester(conn, sem, department_id=department_id)
    stats = {"created": 0, "linked": 0, "skipped": 0}
    buckets: dict[tuple[str, int, int], list[int]] = {}

    for slot in slots:
        if slot.get("teaching_group_id"):
            stats["skipped"] += 1
            continue
        cname = slot["course_name"]
        dept = int(slot.get("department_id") or 0)
        iid = int(slot.get("instructor_id") or 0)
        if dept <= 0 or iid <= 0:
            stats["skipped"] += 1
            continue
        key = (cname.lower(), dept, iid)
        buckets.setdefault(key, []).append(int(slot["section_id"]))

    cur = conn.cursor()
    for (cname_lower, dept, iid), section_ids in buckets.items():
        cname = next(
            (s["course_name"] for s in slots if s["course_name"].lower() == cname_lower),
            cname_lower,
        )
        existing = cur.execute(
            """
            SELECT id FROM teaching_groups
            WHERE lower(trim(course_name)) = lower(trim(?))
              AND semester = ? AND department_id = ?
              AND group_code = ? AND is_active = 1
            LIMIT 1
            """,
            (cname, sem, dept, DEFAULT_GROUP_CODE),
        ).fetchone()
        if existing:
            gid = int(_row_val(existing, 0) or 0)
        else:
            rec = create_teaching_group(
                conn,
                course_name=cname,
                semester=sem,
                department_id=dept,
                instructor_id=iid,
                group_code=DEFAULT_GROUP_CODE,
                group_kind=GROUP_KIND_SINGLE,
            )
            gid = int(rec.get("id") or 0)
            stats["created"] += 1
        if gid:
            stats["linked"] += link_schedule_slots(conn, gid, section_ids)

    return stats


def audit_teaching_groups(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
) -> dict[str, Any]:
    sem = (semester or "").strip()
    if not sem:
        tname, tyear = get_current_term(conn=conn)
        sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()

    slots = _fetch_schedule_slots_for_semester(conn, sem, department_id=department_id)
    groups = list_teaching_groups(conn, semester=sem, department_id=department_id)

    unlinked = [s for s in slots if not s.get("teaching_group_id")]
    no_instructor = [s for s in slots if int(s.get("instructor_id") or 0) <= 0]
    no_dept = [s for s in slots if int(s.get("department_id") or 0) <= 0]
    empty_groups = [g for g in groups if not list_linked_section_ids(conn, int(g["id"]))]

    split_courses: dict[str, list] = {}
    for g in groups:
        if (g.get("group_kind") or "") == GROUP_KIND_SPLIT:
            k = f"{g.get('course_name')}|{g.get('department_id')}"
            split_courses.setdefault(k, []).append(g)

    return {
        "semester": sem,
        "total_slots": len(slots),
        "total_groups": len(groups),
        "unlinked_slots": unlinked,
        "unlinked_count": len(unlinked),
        "slots_without_instructor": no_instructor,
        "slots_without_department": no_dept,
        "empty_groups": empty_groups,
        "split_offerings": [
            {"course_name": v[0].get("course_name"), "department_id": v[0].get("department_id"), "groups": v}
            for v in split_courses.values()
        ],
    }


def teaching_group_labels_map(conn, semester: str | None = None) -> dict[int, str]:
    groups = list_teaching_groups(conn, semester=semester, active_only=True)
    return {int(g["id"]): g.get("display_label") or "" for g in groups if g.get("id")}


def student_department_id(conn, student_id: str) -> int:
    """قسم الطالب: department_id المباشر أو قسم البرنامج الحالي."""
    sid = (student_id or "").strip()
    if not sid or not table_exists(conn, "students"):
        return 0
    cur = conn.cursor()
    cols = {c.lower() for c in fetch_table_columns(conn, "students")}
    dept = 0
    if "department_id" in cols:
        row = cur.execute(
            "SELECT department_id FROM students WHERE student_id = ? LIMIT 1",
            (sid,),
        ).fetchone()
        dept = int(_row_val(row, 0) or 0)
    if dept > 0:
        return dept
    if "current_program_id" in cols and table_exists(conn, "programs"):
        row = cur.execute(
            """
            SELECT p.department_id FROM students s
            JOIN programs p ON p.id = s.current_program_id
            WHERE s.student_id = ? LIMIT 1
            """,
            (sid,),
        ).fetchone()
        dept = int(_row_val(row, 0) or 0)
    return dept


def _course_department_for_student(conn, course_name: str, student_department_id: int) -> int:
    if int(student_department_id or 0) > 0:
        return int(student_department_id)
    if table_exists(conn, "courses"):
        row = conn.cursor().execute(
            "SELECT owning_department_id FROM courses WHERE lower(trim(course_name)) = lower(trim(?)) LIMIT 1",
            ((course_name or "").strip(),),
        ).fetchone()
        return int(_row_val(row, 0) or 0)
    return 0


def list_registration_group_options(
    conn,
    *,
    course_name: str,
    semester: str | None = None,
    student_id: str | None = None,
    department_id: int | None = None,
) -> list[dict[str, Any]]:
    """مجموعات التدريس المتاحة لتسجيل طالب في مقرر (للاختيار عند split)."""
    cname = (course_name or "").strip()
    if not cname or not table_exists(conn, "teaching_groups"):
        return []
    sem = (semester or "").strip()
    if not sem:
        tname, tyear = get_current_term(conn=conn)
        sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
    dept = int(department_id or 0)
    if dept <= 0 and student_id:
        dept = student_department_id(conn, student_id)
    groups = list_teaching_groups(
        conn, semester=sem, department_id=dept if dept > 0 else None, course_name=cname
    )
    if dept > 0:
        groups = [g for g in groups if int(g.get("department_id") or 0) == dept]
    elif student_id:
        sdept = student_department_id(conn, student_id)
        if sdept > 0:
            groups = [g for g in groups if int(g.get("department_id") or 0) == sdept]
    out = []
    for g in groups:
        gid = int(g.get("id") or 0)
        if not gid:
            continue
        out.append({
            **g,
            "teaching_group_id": gid,
            "enrolled_count": count_registrations_for_teaching_group(conn, gid),
        })
    return out


def course_needs_group_choice(conn, course_name: str, semester: str | None, student_id: str) -> bool:
    opts = list_registration_group_options(
        conn, course_name=course_name, semester=semester, student_id=student_id
    )
    if len(opts) <= 1:
        return False
    return any((o.get("group_kind") or "") == GROUP_KIND_SPLIT for o in opts)


def resolve_teaching_group_for_registration(
    conn,
    *,
    student_id: str,
    course_name: str,
    semester: str | None = None,
    teaching_group_id: int | None = None,
    require_explicit_for_split: bool = True,
) -> int | None:
    """
    يحدد teaching_group_id للتسجيل.
    - إن وُجد teaching_group_id: يُتحقق من صلاحيته.
    - إن single أو مجموعة واحدة فقط: يُختار تلقائياً.
    - إن split متعدد: يُطلب اختيار صريح.
    """
    cname = (course_name or "").strip()
    if not cname:
        raise ValueError("course_name مطلوب")
    sem = (semester or "").strip()
    if not sem:
        tname, tyear = get_current_term(conn=conn)
        sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
    opts = list_registration_group_options(
        conn, course_name=cname, semester=sem, student_id=student_id
    )
    if not opts:
        return int(teaching_group_id) if int(teaching_group_id or 0) > 0 else None

    if int(teaching_group_id or 0) > 0:
        valid = {int(o["teaching_group_id"]) for o in opts}
        gid = int(teaching_group_id)
        if gid not in valid:
            raise ValueError(f"مجموعة التدريس غير صالحة للمقرر «{cname}»")
        return gid

    if len(opts) == 1:
        return int(opts[0]["teaching_group_id"])

    singles = [o for o in opts if (o.get("group_kind") or "") == GROUP_KIND_SINGLE]
    if len(singles) == 1:
        return int(singles[0]["teaching_group_id"])

    if require_explicit_for_split and len(opts) > 1:
        raise ValueError(f"اختر مجموعة التدريس (A/B) للمقرر «{cname}»")

    return None


def count_registrations_for_teaching_group(conn, teaching_group_id: int) -> int:
    if not table_exists(conn, "registrations"):
        return 0
    cols = {c.lower() for c in fetch_table_columns(conn, "registrations")}
    if "teaching_group_id" not in cols:
        return 0
    cur = conn.cursor()
    row = cur.execute(
        "SELECT COUNT(DISTINCT student_id) FROM registrations WHERE teaching_group_id = ?",
        (int(teaching_group_id),),
    ).fetchone()
    return int(_row_val(row, 0) or 0)


def backfill_registrations_teaching_groups(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
) -> dict[str, int]:
    """ربط التسجيلات الحالية بمجموعات single الافتراضية."""
    if not table_exists(conn, "registrations"):
        return {"linked": 0, "skipped": 0, "needs_choice": 0}
    cols = {c.lower() for c in fetch_table_columns(conn, "registrations")}
    if "teaching_group_id" not in cols:
        return {"linked": 0, "skipped": 0, "needs_choice": 0}
    sem = (semester or "").strip()
    if not sem:
        tname, tyear = get_current_term(conn=conn)
        sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, student_id, course_name, teaching_group_id
        FROM registrations
        WHERE teaching_group_id IS NULL OR teaching_group_id = 0
        """
    ).fetchall()
    stats = {"linked": 0, "skipped": 0, "needs_choice": 0}
    for row in rows:
        if hasattr(row, "keys"):
            d = dict(row)
            rid = d.get("id")
            sid = d.get("student_id")
            cname = d.get("course_name")
        else:
            rid, sid, cname = row[0], row[1], row[2]
        if department_id is not None:
            sdept = student_department_id(conn, sid)
            if sdept != int(department_id):
                stats["skipped"] += 1
                continue
        try:
            gid = resolve_teaching_group_for_registration(
                conn,
                student_id=sid,
                course_name=cname,
                semester=sem,
                teaching_group_id=None,
                require_explicit_for_split=True,
            )
        except ValueError:
            stats["needs_choice"] += 1
            continue
        if gid:
            cur.execute(
                "UPDATE registrations SET teaching_group_id = ? WHERE id = ?",
                (int(gid), int(rid)),
            )
            stats["linked"] += 1
        else:
            stats["skipped"] += 1
    conn.commit()
    return stats


def registration_teaching_groups_audit(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
) -> dict[str, Any]:
    sem = (semester or "").strip()
    if not sem:
        tname, tyear = get_current_term(conn=conn)
        sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
    cur = conn.cursor()
    cols = {c.lower() for c in fetch_table_columns(conn, "registrations")}
    unlinked: list[dict] = []
    if "teaching_group_id" in cols and table_exists(conn, "registrations"):
        rows = cur.execute(
            """
            SELECT r.student_id, r.course_name, r.teaching_group_id,
                   COALESCE(s.student_name, '') AS student_name
            FROM registrations r
            LEFT JOIN students s ON s.student_id = r.student_id
            WHERE r.teaching_group_id IS NULL OR r.teaching_group_id = 0
            """
        ).fetchall()
        for row in rows:
            if hasattr(row, "keys"):
                d = dict(row)
            else:
                d = {"student_id": row[0], "course_name": row[1], "teaching_group_id": row[2], "student_name": row[3]}
            sid = d.get("student_id")
            cname = d.get("course_name")
            if department_id is not None and student_department_id(conn, sid) != int(department_id):
                continue
            opts = list_registration_group_options(conn, course_name=cname, semester=sem, student_id=sid)
            d["available_groups"] = len(opts)
            d["needs_choice"] = len(opts) > 1
            unlinked.append(d)
    groups = list_teaching_groups(conn, semester=sem, department_id=department_id)
    group_counts = [
        {
            "teaching_group_id": int(g["id"]),
            "display_label": g.get("display_label"),
            "course_name": g.get("course_name"),
            "enrolled_count": count_registrations_for_teaching_group(conn, int(g["id"])),
        }
        for g in groups
        if g.get("id")
    ]
    return {
        "semester": sem,
        "unlinked_registrations": unlinked,
        "unlinked_count": len(unlinked),
        "group_enrollment_counts": group_counts,
    }


def semester_has_teaching_groups(conn, semester: str) -> bool:
    """هل يوجد إعداد مجموعات تدريس للفصل (لتفعيل مسار التقييم/الواجهات الجديد)."""
    sem = (semester or "").strip()
    if not sem or not table_exists(conn, "teaching_groups"):
        return False
    cur = conn.cursor()
    row = cur.execute(
        "SELECT 1 FROM teaching_groups WHERE semester = ? AND is_active = 1 LIMIT 1",
        (sem,),
    ).fetchone()
    return row is not None


def primary_section_id_for_group(conn, teaching_group_id: int) -> int:
    ids = list_linked_section_ids(conn, int(teaching_group_id))
    return min(ids) if ids else 0


def _schedule_slots_for_section_ids(conn, section_ids: list[int]) -> list[dict[str, Any]]:
    if not section_ids or not table_exists(conn, "schedule"):
        return []
    sid_expr = _schedule_section_pk_expr_bare(conn)
    ph = ",".join(["?"] * len(section_ids))
    cur = conn.cursor()
    rows = cur.execute(
        f"""
        SELECT {sid_expr} AS section_id,
               COALESCE(day, '') AS day,
               COALESCE(time, '') AS time,
               COALESCE(room, '') AS room
        FROM schedule
        WHERE {sid_expr} IN ({ph})
        ORDER BY day, time
        """,
        tuple(section_ids),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        if hasattr(row, "keys"):
            d = dict(row)
        else:
            d = {"section_id": row[0], "day": row[1], "time": row[2], "room": row[3]}
        out.append(
            {
                "section_id": int(d.get("section_id") or 0),
                "day": d.get("day") or "",
                "time": d.get("time") or "",
                "room": d.get("room") or "",
            }
        )
    return out


def list_student_evaluable_groups(
    conn,
    student_id: str,
    semester: str,
) -> list[dict[str, Any]]:
    """مجموعات التدريس القابلة للتقييم لطالب في فصل معيّن."""
    sid = (student_id or "").strip()
    sem = (semester or "").strip()
    if not sid or not sem or not table_exists(conn, "registrations"):
        return []
    cur = conn.cursor()
    reg_cols = {c.lower() for c in fetch_table_columns(conn, "registrations")}
    tg_col = "teaching_group_id" in reg_cols
    rows = cur.execute(
        "SELECT course_name, teaching_group_id FROM registrations WHERE student_id = ?"
        if tg_col
        else "SELECT course_name, NULL AS teaching_group_id FROM registrations WHERE student_id = ?",
        (sid,),
    ).fetchall()
    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if hasattr(row, "keys"):
            d = dict(row)
        else:
            d = {"course_name": row[0], "teaching_group_id": row[1] if len(row) > 1 else None}
        cname = (d.get("course_name") or "").strip()
        if not cname:
            continue
        tgid = int(d.get("teaching_group_id") or 0)
        if tgid <= 0:
            try:
                tgid = int(
                    resolve_teaching_group_for_registration(
                        conn,
                        student_id=sid,
                        course_name=cname,
                        semester=sem,
                        teaching_group_id=None,
                        require_explicit_for_split=False,
                    )
                    or 0
                )
            except ValueError:
                continue
        if tgid <= 0 or tgid in seen:
            continue
        g = get_teaching_group(conn, tgid)
        if not g or not int(g.get("is_active") or 0):
            continue
        gsem = (g.get("semester") or "").strip()
        if gsem and sem and not schedule_semester_matches_current_term(gsem, sem):
            continue
        seen.add(tgid)
        sec_id = primary_section_id_for_group(conn, tgid)
        section_ids = list_linked_section_ids(conn, tgid)
        out.append(
            {
                "teaching_group_id": tgid,
                "section_id": sec_id,
                "section_ids": section_ids,
                "course_name": (g.get("course_name") or cname).strip(),
                "instructor_id": int(g.get("instructor_id") or 0),
                "instructor_name": (g.get("instructor_name") or "").strip() or "—",
                "department_id": int(g.get("department_id") or 0),
                "department_name": (g.get("department_name") or "").strip() or "—",
                "group_code": g.get("group_code"),
                "group_code_label": g.get("group_code_label") or group_code_label(g.get("group_code")),
                "group_kind": g.get("group_kind"),
                "display_label": g.get("display_label")
                or format_teaching_group_label(
                    course_name=str(g.get("course_name") or cname),
                    department_name=str(g.get("department_name") or ""),
                    group_code=str(g.get("group_code") or ""),
                    instructor_name=str(g.get("instructor_name") or ""),
                ),
                "semester": sem,
                "schedule_slots": _schedule_slots_for_section_ids(conn, section_ids),
            }
        )
    out.sort(key=lambda x: (x.get("course_name") or "", x.get("group_code_label") or ""))
    return out


def list_instructor_assigned_groups(
    conn,
    instructor_id: int,
    semester: str,
) -> list[dict[str, Any]]:
    """مجموعات التدريس المسندة لأستاذ في فصل معيّن."""
    iid = int(instructor_id or 0)
    sem = (semester or "").strip()
    if iid <= 0 or not sem:
        return []
    groups = list_teaching_groups(conn, semester=sem, active_only=True)
    out: list[dict[str, Any]] = []
    for g in groups:
        if int(g.get("instructor_id") or 0) != iid:
            continue
        tgid = int(g.get("id") or 0)
        if not tgid:
            continue
        section_ids = list_linked_section_ids(conn, tgid)
        slots = _schedule_slots_for_section_ids(conn, section_ids)
        sec_id = min(section_ids) if section_ids else 0
        day = " — ".join(
            dict.fromkeys(f"{s.get('day') or ''} {s.get('time') or ''}".strip() for s in slots)
        ) if len(slots) > 1 else (f"{slots[0].get('day') or ''} {slots[0].get('time') or ''}".strip() if slots else "")
        rooms = [str(s.get("room") or "").strip() for s in slots if s.get("room")]
        out.append(
            {
                "teaching_group_id": tgid,
                "section_id": sec_id,
                "section_ids": section_ids,
                "course_name": (g.get("course_name") or "").strip(),
                "day": day,
                "time": slots[0].get("time") if len(slots) == 1 else "",
                "room": " / ".join(dict.fromkeys(r for r in rooms if r)) if rooms else "",
                "instructor": (g.get("instructor_name") or "").strip(),
                "instructor_id": iid,
                "semester": sem,
                "department_id": int(g.get("department_id") or 0),
                "department_name": (g.get("department_name") or "").strip() or "—",
                "group_code": g.get("group_code"),
                "group_code_label": g.get("group_code_label") or group_code_label(g.get("group_code")),
                "group_kind": g.get("group_kind"),
                "display_label": g.get("display_label") or "",
                "schedule_slots": slots,
                "student_count": count_registrations_for_teaching_group(conn, tgid),
            }
        )
    out.sort(key=lambda x: (x.get("course_name") or "", x.get("group_code_label") or ""))
    return out


def backfill_course_evaluations_teaching_groups(
    conn,
    *,
    semester: str | None = None,
) -> dict[str, int]:
    """ربط تقييمات قديمة بمجموعات التدريس عبر التسجيل أو الجدول."""
    if not table_exists(conn, "course_evaluations"):
        return {"linked": 0, "skipped": 0}
    cols = {c.lower() for c in fetch_table_columns(conn, "course_evaluations")}
    if "teaching_group_id" not in cols:
        return {"linked": 0, "skipped": 0}
    sem = (semester or "").strip()
    if not sem:
        tname, tyear = get_current_term(conn=conn)
        sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
    cur = conn.cursor()
    reg_cols = {c.lower() for c in fetch_table_columns(conn, "registrations")}
    rows = cur.execute(
        """
        SELECT id, student_id, section_id, course_name, instructor_id, semester, teaching_group_id
        FROM course_evaluations
        WHERE teaching_group_id IS NULL OR teaching_group_id = 0
        """
    ).fetchall()
    stats = {"linked": 0, "skipped": 0}
    for row in rows:
        if hasattr(row, "keys"):
            d = dict(row)
        else:
            d = {
                "id": row[0],
                "student_id": row[1],
                "section_id": row[2],
                "course_name": row[3],
                "instructor_id": row[4],
                "semester": row[5],
                "teaching_group_id": row[6] if len(row) > 6 else None,
            }
        ev_sem = (d.get("semester") or "").strip()
        if sem and ev_sem and not schedule_semester_matches_current_term(ev_sem, sem):
            stats["skipped"] += 1
            continue
        rid = int(d.get("id") or 0)
        sid = (d.get("student_id") or "").strip()
        cname = (d.get("course_name") or "").strip()
        tgid = 0
        if "teaching_group_id" in reg_cols:
            rrow = cur.execute(
                """
                SELECT teaching_group_id FROM registrations
                WHERE student_id = ? AND lower(trim(course_name)) = lower(trim(?))
                  AND teaching_group_id IS NOT NULL AND teaching_group_id > 0
                LIMIT 1
                """,
                (sid, cname),
            ).fetchone()
            tgid = int(_row_val(rrow, 0) or 0)
        if tgid <= 0:
            try:
                tgid = int(
                    resolve_teaching_group_for_registration(
                        conn,
                        student_id=sid,
                        course_name=cname,
                        semester=ev_sem or sem,
                        require_explicit_for_split=False,
                    )
                    or 0
                )
            except ValueError:
                tgid = 0
        if tgid <= 0 and int(d.get("section_id") or 0) > 0 and table_exists(conn, "schedule"):
            sid_expr = _schedule_section_pk_expr_bare(conn)
            srow = cur.execute(
                f"SELECT teaching_group_id FROM schedule WHERE {sid_expr} = ? LIMIT 1",
                (int(d["section_id"]),),
            ).fetchone()
            tgid = int(_row_val(srow, 0) or 0)
        if tgid > 0:
            cur.execute(
                "UPDATE course_evaluations SET teaching_group_id = ? WHERE id = ?",
                (tgid, rid),
            )
            stats["linked"] += 1
        else:
            stats["skipped"] += 1
    conn.commit()
    return stats


def teaching_groups_without_evaluation_audit(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
) -> dict[str, Any]:
    """مجموعات تدريس بلا أي تقييم مقرر في الفصل."""
    sem = (semester or "").strip()
    if not sem:
        tname, tyear = get_current_term(conn=conn)
        sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
    groups = list_teaching_groups(conn, semester=sem, department_id=department_id, active_only=True)
    evaluated_tg: set[int] = set()
    evaluated_ci: set[tuple[str, int]] = set()
    if table_exists(conn, "course_evaluations"):
        cur = conn.cursor()
        ce_cols = {c.lower() for c in fetch_table_columns(conn, "course_evaluations")}
        dept_sql = ""
        params: list[Any] = [sem]
        if department_id is not None:
            dept_sql = " AND EXISTS (SELECT 1 FROM teaching_groups tg WHERE tg.id = e.teaching_group_id AND tg.department_id = ?) "
            params.append(int(department_id))
        if "teaching_group_id" in ce_cols:
            for row in cur.execute(
                f"""
                SELECT DISTINCT teaching_group_id FROM course_evaluations e
                WHERE e.semester = ? AND teaching_group_id IS NOT NULL AND teaching_group_id > 0 {dept_sql}
                """,
                tuple(params),
            ).fetchall():
                tgid = int(_row_val(row, 0) or 0)
                if tgid:
                    evaluated_tg.add(tgid)
        for row in cur.execute(
            """
            SELECT DISTINCT lower(trim(course_name)), instructor_id
            FROM course_evaluations e
            WHERE e.semester = ?
            """,
            (sem,),
        ).fetchall():
            ck = (_row_val(row, 0) or "").strip().lower()
            eiid = int(_row_val(row, 1) or 0)
            if ck and eiid > 0:
                evaluated_ci.add((ck, eiid))

    missing: list[dict[str, Any]] = []
    for g in groups:
        tgid = int(g.get("id") or 0)
        if not tgid:
            continue
        ckey = (str(g.get("course_name") or "").strip().lower(), int(g.get("instructor_id") or 0))
        if tgid in evaluated_tg or ckey in evaluated_ci:
            continue
        enrolled = count_registrations_for_teaching_group(conn, tgid)
        missing.append(
            {
                "teaching_group_id": tgid,
                "course_name": g.get("course_name"),
                "instructor_id": int(g.get("instructor_id") or 0),
                "instructor_name": g.get("instructor_name") or "—",
                "department_name": g.get("department_name") or "—",
                "group_code_label": g.get("group_code_label") or group_code_label(g.get("group_code")),
                "display_label": g.get("display_label") or "",
                "enrolled_count": enrolled,
                "eligible_for_student": enrolled > 0 and int(g.get("instructor_id") or 0) > 0,
                "gap_reasons": ["لم يُرسَل أي تقييم"]
                + ([] if enrolled > 0 else ["بلا تسجيلات طلاب للمجموعة"]),
                "gap_reasons_ar": "",
            }
        )
        missing[-1]["gap_reasons_ar"] = "؛ ".join(missing[-1]["gap_reasons"])
    return {
        "semester": sem,
        "department_id": department_id,
        "total_teaching_groups": len(groups),
        "evaluated_groups": len(groups) - len(missing),
        "missing_groups": len(missing),
        "rows": missing,
    }
