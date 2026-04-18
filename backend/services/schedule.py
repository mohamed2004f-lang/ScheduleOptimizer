import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from flask import Blueprint, request, jsonify, render_template, session
from backend.core.auth import login_required, role_required, current_supervisor_effective
from collections import defaultdict
import pandas as pd
import logging
import json
import datetime
import base64
from backend.database.database import is_postgresql, schedule_pk_column
from backend.core.exceptions import ValidationError
from backend.core.faculty_axes import (
    FACULTY_AXIS_KEYS,
    VALID_AXIS_STATUS,
    axis_labels_for_api,
    normalize_instructor_name,
)

from .utilities import (
    get_connection,
    SEMESTER_LABEL,
    excel_response_from_df,
    pdf_response_from_html,
    log_activity,
    get_schedule_published_at,
    set_schedule_published_at,
    get_schedule_updated_at,
    touch_schedule_updated_at,
    get_current_term,
    schedule_semester_matches_current_term,
)
from .students import compute_per_student_conflicts, recompute_conflict_report

logger = logging.getLogger(__name__)

schedule_bp = Blueprint("schedule", __name__)
SCHEDULE_PK_COL = "id"


def _sync_schedule_pk_col(conn):
    global SCHEDULE_PK_COL
    try:
        SCHEDULE_PK_COL = schedule_pk_column(conn)
    except Exception:
        pass
    return SCHEDULE_PK_COL
VALID_LECTURE_STATUS = frozenset({"planned", "done", "postponed", "compensated"})
VALID_ANNOUNCEMENT_TYPES = frozenset({"general", "postponement", "makeup", "extra_lecture"})
VALID_FACULTY_ASSIGNMENT_TYPES = frozenset({"course", "committee", "service", "quality", "supervision"})
VALID_FACULTY_LOG_TYPES = frozenset({"communication", "supervision_session", "quality_report"})
VALID_FACULTY_LOG_APPROVAL = frozenset({"draft", "submitted", "approved", "rejected"})


def _current_term_label_safe(conn) -> str:
    try:
        tname, tyear = get_current_term(conn=conn)
        return f"{(tname or '').strip()} {(tyear or '').strip()}".strip() or SEMESTER_LABEL
    except Exception:
        return SEMESTER_LABEL


def _faculty_cycle_lock_key(term_label: str) -> str:
    return f"faculty_cycle_lock::{(term_label or '').strip()}"


def _is_faculty_cycle_locked(conn, term_label: str) -> bool:
    key = _faculty_cycle_lock_key(term_label)
    row = conn.cursor().execute(
        "SELECT COALESCE(value_json,'false') FROM app_settings WHERE key = ? LIMIT 1",
        (key,),
    ).fetchone()
    val = (row[0] if row else "false") or "false"
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _set_faculty_cycle_locked(conn, term_label: str, locked: bool, actor: str):
    key = _faculty_cycle_lock_key(term_label)
    now = datetime.datetime.utcnow().isoformat()
    conn.cursor().execute(
        """
        INSERT INTO app_settings (key, value_json, updated_at, updated_by)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (key) DO UPDATE SET
            value_json = EXCLUDED.value_json,
            updated_at = EXCLUDED.updated_at,
            updated_by = EXCLUDED.updated_by
        """,
        (key, "true" if locked else "false", now, actor),
    )
    conn.commit()


def _append_governance_audit(conn, actor: str, action: str, scope_type: str, scope_id: str, old_value: str = "", new_value: str = "", reason: str = ""):
    now = datetime.datetime.utcnow().isoformat()
    conn.cursor().execute(
        """
        INSERT INTO governance_audit_logs (ts, actor, action, scope_type, scope_id, old_value, new_value, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (now, actor or "", action or "", scope_type or "", scope_id or "", old_value or "", new_value or "", reason or ""),
    )


def _has_section_evidence(cur, section_id: int, instructor_id: int) -> bool:
    plan = cur.execute(
        """
        SELECT 1 FROM faculty_course_plans
        WHERE section_id = ? AND instructor_id = ?
          AND COALESCE(lecture_status,'planned') IN ('done', 'compensated')
        LIMIT 1
        """,
        (section_id, instructor_id),
    ).fetchone()
    if plan:
        return True
    ann = cur.execute(
        """
        SELECT 1 FROM faculty_course_announcements
        WHERE section_id = ? AND instructor_id = ?
        LIMIT 1
        """,
        (section_id, instructor_id),
    ).fetchone()
    if ann:
        return True
    closure = cur.execute(
        """
        SELECT 1 FROM course_closure_reports
        WHERE section_id = ? AND instructor_id = ?
          AND COALESCE(status,'draft') IN ('submitted', 'approved')
        LIMIT 1
        """,
        (section_id, instructor_id),
    ).fetchone()
    if closure:
        return True
    log_ok = cur.execute(
        """
        SELECT 1
        FROM faculty_assignment_logs l
        JOIN faculty_assignments a ON a.id = l.assignment_id
        WHERE l.instructor_id = ?
          AND COALESCE(l.approval_status,'draft') = 'approved'
          AND (l.section_id = ? OR a.section_id = ?)
        LIMIT 1
        """,
        (instructor_id, section_id, section_id),
    ).fetchone()
    return bool(log_ok)


def _ensure_schedule_version_tables(cur):
    # الجداول تُنشأ عبر Alembic على PostgreSQL؛ DDL الخاص بـ SQLite هنا يفشل (AUTOINCREMENT).
    if is_postgresql():
        return
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            version_no INTEGER NOT NULL DEFAULT 1,
            snapshot_json TEXT DEFAULT '',
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            generated_by TEXT DEFAULT '',
            note TEXT DEFAULT '',
            is_published INTEGER NOT NULL DEFAULT 0,
            UNIQUE (semester, version_no)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_version_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_version_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_time TEXT DEFAULT CURRENT_TIMESTAMP,
            actor TEXT DEFAULT '',
            details TEXT DEFAULT ''
        )
        """
    )


def _create_schedule_version(conn, event_type: str, note: str = "", is_published: bool = False):
    _sync_schedule_pk_col(conn)
    cur = conn.cursor()
    _ensure_schedule_version_tables(cur)
    try:
        tname, tyear = get_current_term(conn=conn)
        semester = f"{(tname or '').strip()} {(tyear or '').strip()}".strip() or SEMESTER_LABEL
    except Exception:
        semester = SEMESTER_LABEL

    rows = cur.execute(
        f"""
        SELECT {SCHEDULE_PK_COL}, COALESCE(course_name,''), COALESCE(day,''), COALESCE(time,''),
               COALESCE(room,''), COALESCE(instructor,''), COALESCE(semester,'')
        FROM schedule
        ORDER BY day, time, course_name, {SCHEDULE_PK_COL}
        """
    ).fetchall()
    items = []
    for r in rows:
        items.append(
            {
                "section_id": int(r[0]),
                "course_name": r[1],
                "day": r[2],
                "time": r[3],
                "room": r[4],
                "instructor": r[5],
                "semester": r[6],
            }
        )

    actor = (session.get("user") or session.get("username") or "").strip() or "system"
    now = datetime.datetime.utcnow().isoformat()
    max_row = cur.execute(
        "SELECT COALESCE(MAX(version_no),0) FROM schedule_versions WHERE semester = ?",
        (semester,),
    ).fetchone()
    version_no = int((max_row[0] if max_row and max_row[0] is not None else 0) or 0) + 1
    snapshot = {
        "semester": semester,
        "captured_at": now,
        "captured_by": actor,
        "row_count": len(items),
        "rows": items,
    }
    if is_postgresql():
        row_new = cur.execute(
            """
            INSERT INTO schedule_versions
            (semester, version_no, snapshot_json, generated_at, generated_by, note, is_published)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                semester,
                version_no,
                json.dumps(snapshot, ensure_ascii=False),
                now,
                actor,
                (note or ""),
                1 if is_published else 0,
            ),
        ).fetchone()
        ver_id = int(row_new[0]) if row_new else 0
    else:
        cur.execute(
            """
            INSERT INTO schedule_versions
            (semester, version_no, snapshot_json, generated_at, generated_by, note, is_published)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                semester,
                version_no,
                json.dumps(snapshot, ensure_ascii=False),
                now,
                actor,
                (note or ""),
                1 if is_published else 0,
            ),
        )
        ver_id = int(cur.lastrowid or 0)
    cur.execute(
        """
        INSERT INTO schedule_version_events
        (schedule_version_id, event_type, event_time, actor, details)
        VALUES (?, ?, ?, ?, ?)
        """,
        (ver_id, (event_type or "manual"), now, actor, (note or "")),
    )
    conn.commit()
    return {"id": ver_id, "semester": semester, "version_no": version_no, "generated_at": now}

def _time_to_minutes_hhmm(s: str):
    try:
        s = (s or "").strip()
        if len(s) != 5 or s[2] != ":":
            return None
        hh = int(s[0:2])
        mm = int(s[3:5])
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh * 60 + mm
    except Exception:
        return None
    return None


def _parse_time_range_to_minutes(time_str: str):
    """
    يدعم: 09:00-13:00 ، 13:00-09:00 ، 09:00 - 11:00 ، 09:00/11:00 ...
    يرجع (start_min, end_min) أو (None, None)
    """
    if not time_str:
        return (None, None)
    v = str(time_str).strip()
    for sep in ["-", "–", "—", "/", "\\", " to "]:
        if sep in v:
            parts = [p.strip() for p in v.split(sep, 1)]
            if len(parts) == 2:
                a = _time_to_minutes_hhmm(parts[0])
                b = _time_to_minutes_hhmm(parts[1])
                if a is None or b is None:
                    return (None, None)
                if b < a:
                    a, b = b, a
                return (a, b)
    # single
    a = _time_to_minutes_hhmm(v)
    return (a, a) if a is not None else (None, None)


def _ranges_overlap(a1, a2, b1, b2) -> bool:
    if a1 is None or a2 is None or b1 is None or b2 is None:
        return False
    return max(a1, b1) < min(a2, b2)


def _current_term_key_suffix(conn) -> str:
    name, year = get_current_term(conn=conn)
    label = f"{(name or '').strip()} {(year or '').strip()}".strip()
    return label or "UNKNOWN_TERM"


def _now_iso_z() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _setting_key_time_slots(conn) -> str:
    return "time_slots::" + _current_term_key_suffix(conn)


def _default_time_slots() -> list:
    return [
        "09:00-11:00",
        "11:00-12:00",
        "12:00-13:00",
        "13:00-14:00",
        "14:00-15:00",
        "15:00-16:00",
        "16:00-17:00",
    ]


def _normalize_time_slot_str(s: str) -> str:
    return (s or "").strip()


def _validate_time_slot_format(s: str) -> bool:
    # صيغة بسيطة: HH:MM-HH:MM
    try:
        s = _normalize_time_slot_str(s)
        if not s or "-" not in s:
            return False
        a, b = [p.strip() for p in s.split("-", 1)]
        def ok(p):
            if len(p) != 5 or p[2] != ":":
                return False
            hh = int(p[0:2])
            mm = int(p[3:5])
            return 0 <= hh <= 23 and 0 <= mm <= 59
        return ok(a) and ok(b)
    except Exception:
        return False


def _get_time_slots_setting(conn) -> dict:
    """يرجع {slots, source, key, term_label}"""
    key = _setting_key_time_slots(conn)
    term_label = _current_term_key_suffix(conn)
    cur = conn.cursor()
    row = cur.execute("SELECT value_json FROM app_settings WHERE key = ? LIMIT 1", (key,)).fetchone()
    if row and (row[0] if isinstance(row, (list, tuple)) else row["value_json"]):
        raw = (row[0] if isinstance(row, (list, tuple)) else row["value_json"]) or ""
        try:
            data = json.loads(raw)
            slots = data.get("slots") if isinstance(data, dict) else data
            if isinstance(slots, list):
                slots = [_normalize_time_slot_str(x) for x in slots]
                slots = [x for x in slots if x]
                return {"slots": slots, "source": "saved", "key": key, "term_label": term_label}
        except Exception:
            pass
    return {"slots": _default_time_slots(), "source": "default", "key": key, "term_label": term_label}


def _days_ar() -> list:
    return ['السبت', 'الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس']


def _build_schedule_matrix(rows: list, time_slots: list, include_empty: bool) -> dict:
    """
    يبني مصفوفة {day -> {time -> [rows]}} مع تقرير ملحق عن الأوقات الفارغة/غير المطابقة.
    rows: dicts من schedule (day,time,course_name,...)
    """
    # Normalize
    slots_saved = [str(t or "").strip() for t in (time_slots or []) if str(t or "").strip()]
    times_in_data = sorted({str(r.get("time") or "").strip() for r in (rows or []) if str(r.get("time") or "").strip()})

    # أعمدة العرض
    if include_empty:
        columns = list(dict.fromkeys(slots_saved + times_in_data))  # keep order, add nonmatching after
    else:
        # فقط أوقات لديها صفوف + أوقات غير مطابقة لديها صفوف (مضمونة ضمن times_in_data)
        columns = list(times_in_data)
        # نحافظ على ترتيب مقروء: وفق saved slots أولاً ثم باقي الأوقات
        ordered = []
        in_set = set(columns)
        for s in slots_saved:
            if s in in_set and s not in ordered:
                ordered.append(s)
        for t in columns:
            if t not in ordered:
                ordered.append(t)
        columns = ordered

    slot_set = set(slots_saved)
    nonmatching_with_rows = [t for t in times_in_data if t not in slot_set]

    # أوقات محفوظة لكنها فارغة (لا يوجد أي صف بها)
    empty_saved = []
    if slots_saved:
        data_set = set(times_in_data)
        empty_saved = [s for s in slots_saved if s not in data_set]

    # Map day/time -> list of display strings
    matrix = {d: {t: [] for t in columns} for d in _days_ar()}
    for r in rows or []:
        day = str(r.get("day") or "").strip()
        time = str(r.get("time") or "").strip()
        if not day or not time:
            continue
        if day not in matrix:
            # أحياناً قد توجد تسميات مختلفة؛ أنشئها
            if day not in matrix:
                matrix[day] = {t: [] for t in columns}
        if time not in columns:
            # إذا تغيّرت الأعمدة بعد بناء المصفوفة، تجاهل
            continue
        name = (r.get("course_name") or "").strip()
        room = (r.get("room") or "").strip()
        inst = (r.get("instructor") or "").strip()
        extras = []
        if room:
            extras.append(f"ق {room}")
        if inst:
            extras.append(inst)
        suffix = (" — " + " — ".join(extras)) if extras else ""
        matrix[day][time].append(f"{name}{suffix}" if name else suffix.strip(" —"))

    return {
        "columns": columns,
        "matrix": matrix,
        "empty_saved_slots": empty_saved,
        "nonmatching_times": nonmatching_with_rows,
        "times_in_data": times_in_data,
        "saved_slots": slots_saved,
    }


def _load_schedule_rows_for_export(conn) -> list:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT COALESCE(course_name,'') AS course_name,
               COALESCE(day,'') AS day,
               COALESCE(time,'') AS time,
               COALESCE(room,'') AS room,
               COALESCE(instructor,'') AS instructor,
               COALESCE(semester,'') AS semester
        FROM schedule
        WHERE COALESCE(course_name,'') <> ''
          AND COALESCE(day,'') <> ''
          AND COALESCE(time,'') <> ''
        """
    ).fetchall()
    return [dict(r) for r in rows] if rows else []


def _build_schedule_triple_export_matrix(rows: list, time_slots: list, include_empty: bool) -> dict:
    """
    مصفوفة خاصة بالتصدير:
    { day -> { time -> [ {course_name, instructor, room} ] } }
    ليتم عرض التصدير بنفس تنسيق واجهة الجدول (مقرر|أستاذ|قاعة لكل توقيت).
    """
    slots_saved = [str(t or "").strip() for t in (time_slots or []) if str(t or "").strip()]
    times_in_data = sorted({str(r.get("time") or "").strip() for r in (rows or []) if str(r.get("time") or "").strip()})

    if include_empty:
        columns = list(dict.fromkeys(slots_saved + times_in_data))
    else:
        columns = list(times_in_data)
        ordered = []
        in_set = set(columns)
        for s in slots_saved:
            if s in in_set and s not in ordered:
                ordered.append(s)
        for t in columns:
            if t not in ordered:
                ordered.append(t)
        columns = ordered

    slot_set = set(slots_saved)
    nonmatching_with_rows = [t for t in times_in_data if t not in slot_set]

    empty_saved = []
    if slots_saved:
        data_set = set(times_in_data)
        empty_saved = [s for s in slots_saved if s not in data_set]

    matrix = {d: {t: [] for t in columns} for d in _days_ar()}

    ordered_rows = sorted(
        rows or [],
        key=lambda r: (
            str(r.get("day") or "").strip(),
            str(r.get("time") or "").strip(),
            str(r.get("course_name") or "").strip(),
            str(r.get("instructor") or "").strip(),
            str(r.get("room") or "").strip(),
        ),
    )

    for r in ordered_rows:
        day = str(r.get("day") or "").strip()
        time = str(r.get("time") or "").strip()
        if not day or not time:
            continue
        if day not in matrix or time not in columns:
            continue
        matrix[day][time].append(
            {
                "course_name": str(r.get("course_name") or "").strip(),
                "instructor": str(r.get("instructor") or "").strip(),
                "room": str(r.get("room") or "").strip(),
            }
        )

    return {
        "columns": columns,
        "matrix": matrix,
        "empty_saved_slots": empty_saved,
        "nonmatching_times": nonmatching_with_rows,
        "times_in_data": times_in_data,
        "saved_slots": slots_saved,
    }

# -----------------------------
# عرض/إضافة صفوف الجدول
# -----------------------------

@schedule_bp.route("/rows")
@login_required
def list_schedule_rows():
    with get_connection() as conn:
        _sync_schedule_pk_col(conn)
        cur = conn.cursor()
        try:
            # استخدام JOIN لتحسين الأداء بدلاً من استعلامات منفصلة في loop
            rows = cur.execute(f"""
                SELECT 
                    s.{SCHEDULE_PK_COL} AS section_id, 
                    s.course_name, 
                    s.day, 
                    s.time, 
                    s.room, 
                    s.instructor, 
                    s.semester,
                    s.instructor_id,
                    COUNT(DISTINCT r.student_id) AS student_count
                FROM schedule s
                LEFT JOIN registrations r ON s.course_name = r.course_name
                GROUP BY s.{SCHEDULE_PK_COL}, s.course_name, s.day, s.time, s.room, s.instructor, s.semester, s.instructor_id
                ORDER BY s.{SCHEDULE_PK_COL}
            """).fetchall()
            result = []
            for r in rows:
                result.append({
                    'section_id': r[0],
                    'course_name': r[1],
                    'day': r[2],
                    'time': r[3],
                    'room': r[4],
                    'instructor': r[5],
                    'semester': r[6],
                    'instructor_id': r[7],
                    'student_count': r[8] or 0
                })
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error in list_schedule_rows: {e}")
            return jsonify([])

# Alias to match frontend calls that use /list_schedule_rows
@schedule_bp.route("/list_schedule_rows")
@login_required
def list_schedule_rows_alias():
    return list_schedule_rows()


@schedule_bp.route("/instructor_conflicts")
@login_required
def instructor_conflicts():
    """
    تعارضات الأساتذة (Double booking):
    نفس الأستاذ لديه مقرران أو أكثر بنفس اليوم مع تداخل زمني.
    Returns:
      { status:'ok', conflicts:[{instructor, day, start_time, end_time, entries:[{section_id, course_name, time}]}] }
    """
    try:
        with get_connection() as conn:
            _sync_schedule_pk_col(conn)
            cur = conn.cursor()
            rows = cur.execute(
                f"""
                SELECT
                  s.{SCHEDULE_PK_COL} AS section_id,
                  COALESCE(s.course_name,'') AS course_name,
                  COALESCE(s.day,'') AS day,
                  COALESCE(s.time,'') AS time,
                  COALESCE(s.instructor,'') AS instructor
                FROM schedule s
                WHERE COALESCE(s.instructor,'') <> ''
                  AND COALESCE(s.day,'') <> ''
                  AND COALESCE(s.time,'') <> ''
                """
            ).fetchall()

        items = []
        for r in rows or []:
            d = dict(r)
            start_min, end_min = _parse_time_range_to_minutes(d.get("time") or "")
            if start_min is None or end_min is None:
                continue
            items.append({
                "section_id": d.get("section_id"),
                "course_name": (d.get("course_name") or "").strip(),
                "day": (d.get("day") or "").strip(),
                "time": (d.get("time") or "").strip(),
                "instructor": (d.get("instructor") or "").strip(),
                "start_min": start_min,
                "end_min": end_min,
            })

        # group by (instructor, day)
        by_key = defaultdict(list)
        for it in items:
            by_key[(it["instructor"], it["day"])].append(it)

        out = []
        for (inst, day), lst in by_key.items():
            # detect overlap groups
            lst = sorted(lst, key=lambda x: (x["start_min"], x["end_min"], x["course_name"]))
            n = len(lst)
            if n < 2:
                continue

            # build graph edges on overlap
            adj = [[] for _ in range(n)]
            for i in range(n):
                for j in range(i + 1, n):
                    if _ranges_overlap(lst[i]["start_min"], lst[i]["end_min"], lst[j]["start_min"], lst[j]["end_min"]):
                        adj[i].append(j)
                        adj[j].append(i)

            seen = set()
            for i in range(n):
                if i in seen or not adj[i]:
                    continue
                # BFS component
                stack = [i]
                comp = []
                seen.add(i)
                while stack:
                    u = stack.pop()
                    comp.append(u)
                    for v in adj[u]:
                        if v not in seen:
                            seen.add(v)
                            stack.append(v)
                if len(comp) < 2:
                    continue
                comp_items = [lst[idx] for idx in comp]
                start_min = min(x["start_min"] for x in comp_items)
                end_min = max(x["end_min"] for x in comp_items)
                out.append({
                    "instructor": inst,
                    "day": day,
                    "start_time": f"{start_min//60:02d}:{start_min%60:02d}",
                    "end_time": f"{end_min//60:02d}:{end_min%60:02d}",
                    "entries": [
                        {"section_id": x["section_id"], "course_name": x["course_name"], "time": x["time"]}
                        for x in sorted(comp_items, key=lambda x: (x["start_min"], x["end_min"], x["course_name"]))
                    ],
                })

        return jsonify({"status": "ok", "conflicts": out}), 200
    except Exception as e:
        logger.error(f"instructor_conflicts failed: {e}", exc_info=True)
        return jsonify({"status": "ok", "conflicts": []}), 200

@schedule_bp.route("/check_conflicts", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def check_conflicts():
    """
    التحقق من التعارضات قبل إضافة مقرر جديد
    Returns: قائمة بالتعارضات المحتملة
    """
    try:
        data = request.get_json(force=True) or {}
        course_name = data.get("course_name", "").strip()
        day = data.get("day", "").strip()
        time = data.get("time", "").strip()
        
        if not course_name or not day or not time:
            return jsonify({
                "status": "error",
                "message": "بيانات غير كاملة"
            }), 400
        
        # محاكاة إضافة المقرر مؤقتاً للتحقق من التعارضات (بفصل حالي صريح)
        with get_connection() as conn:
            term_name, term_year = get_current_term(conn=conn)
            semester_label = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()
            if not semester_label:
                return jsonify({"status": "error", "message": "يجب تحديد الفصل الحالي أولاً من الإعدادات"}), 400
            # حفظ حالة الجدول الحالي
            cur = conn.cursor()
            
            # إضافة مؤقتة للجدول
            _iid = data.get("instructor_id")
            try:
                _iid = int(_iid) if _iid is not None and _iid != "" else None
            except (TypeError, ValueError):
                _iid = None
            if is_postgresql():
                row_new = cur.execute(
                    f"""
                    INSERT INTO schedule (course_name, day, time, room, instructor, instructor_id, semester)
                    VALUES (?,?,?,?,?,?,?)
                    RETURNING {SCHEDULE_PK_COL}
                    """,
                    (
                        course_name,
                        day,
                        time,
                        data.get("room", ""),
                        data.get("instructor", ""),
                        _iid,
                        (data.get("semester") or "").strip() or semester_label
                    ),
                ).fetchone()
                temp_rowid = int(row_new[0]) if row_new else 0
            else:
                cur.execute(
                    """
                    INSERT INTO schedule (course_name, day, time, room, instructor, instructor_id, semester)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        course_name,
                        day,
                        time,
                        data.get("room", ""),
                        data.get("instructor", ""),
                        _iid,
                        (data.get("semester") or "").strip() or semester_label
                    ),
                )
                temp_rowid = int(cur.lastrowid or 0)
            
            # حساب التعارضات
            conflicts = compute_per_student_conflicts(conn)
            
            # حذف الإضافة المؤقتة
            cur.execute(f"DELETE FROM schedule WHERE {SCHEDULE_PK_COL} = ?", (temp_rowid,))
            conn.commit()
            
            # تصفية التعارضات المتعلقة بالمقرر الجديد
            relevant_conflicts = []
            for conflict in conflicts:
                # التحقق إذا كان التعارض يتضمن المقرر الجديد
                conflicting_sections = conflict.get('conflicting_sections', '')
                # لا نعتمد على تطابق نصي للوقت لأن الوقت يُخزّن بأكثر من صيغة (مثلاً 09:00-13:00 مقابل 09:00-11:00).
                # يكفينا تحقق: اليوم + مشاركة المقرر الجديد ضمن المقررات المتعارضة.
                if course_name in conflicting_sections and day == conflict.get('day'):
                    relevant_conflicts.append({
                        'student_id': conflict.get('student_id', ''),
                        'day': conflict.get('day', ''),
                        'time': time,
                        'conflicting_sections': conflicting_sections
                    })

            # إحضار أسماء الطلبة لتظهر في نافذة التعارضات
            try:
                student_ids = sorted({(c.get("student_id") or "").strip() for c in relevant_conflicts if (c.get("student_id") or "").strip()})
                name_map = {}
                if student_ids:
                    rows2 = cur.execute(
                        "SELECT student_id, COALESCE(student_name,'') as student_name FROM students WHERE student_id IN ({})".format(
                            ",".join("?" for _ in student_ids)
                        ),
                        student_ids,
                    ).fetchall()
                    name_map = {r[0]: (r[1] or "") for r in rows2}

                for c in relevant_conflicts:
                    sid = (c.get("student_id") or "").strip()
                    c["student_name"] = name_map.get(sid, "")
            except Exception:
                # في حال فشل الاستعلام، نترك student_name فارغاً بدون كسر الواجهة
                pass
            
            return jsonify({
                "status": "ok",
                "has_conflicts": len(relevant_conflicts) > 0,
                "conflicts": relevant_conflicts,
                "conflict_count": len(relevant_conflicts)
            }), 200
            
    except Exception as e:
        logger.error(f"Error checking conflicts: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"خطأ في التحقق من التعارضات: {str(e)}"
        }), 500

# Original add_row (kept)
def _parse_instructor_id_payload(raw):
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@schedule_bp.route("/add_row", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def add_schedule_row():
    data = request.get_json(force=True)
    required = ["course_name", "day", "time"]
    for k in required:
        if not data.get(k):
            return jsonify({"status": "error", "message": f"{k} مطلوب"}), 400
    try:
        from backend.core.services import ScheduleService

        sem = (data.get("semester") or "").strip()
        if not sem:
            with get_connection() as conn:
                tname, tyear = get_current_term(conn=conn)
            sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
        if not sem:
            return jsonify({"status": "error", "message": "يجب تحديد الفصل الحالي أولاً من الإعدادات"}), 400

        res = ScheduleService.add_schedule_row(
            data.get("course_name"),
            data.get("day"),
            data.get("time"),
            room=data.get("room", ""),
            instructor=data.get("instructor", ""),
            semester=sem,
            instructor_id=_parse_instructor_id_payload(data.get("instructor_id")),
        )
        last = res.get("section_id")
        try:
            with get_connection() as conn:
                touch_schedule_updated_at(conn)
        except Exception:
            pass
    except ValidationError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        logger.exception("add_schedule_row failed")
        return jsonify({"status": "error", "message": str(e)}), 400

    try:
        log_activity(
            action="add_schedule_row",
            details=f"section_id={last}, course_name={data.get('course_name')}, day={data.get('day')}, time={data.get('time')}",
        )
    except Exception:
        pass
    return jsonify({"status": "ok", "message": "تم إضافة صف إلى الجدول", "section_id": last}), 200

# Alias to match frontend calls that use /add_schedule_row
@schedule_bp.route("/add_schedule_row", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def add_schedule_row_alias():
    return add_schedule_row()


@schedule_bp.route("/delete_schedule_row", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def delete_schedule_row():
    """حذف صف من الجدول الدراسي (للأدمن فقط)."""
    data = request.get_json(force=True) or {}
    section_id = data.get("section_id")
    try:
        from backend.core.services import ScheduleService
        res = ScheduleService.delete_schedule_row(int(section_id))
        try:
            with get_connection() as conn:
                touch_schedule_updated_at(conn)
        except Exception:
            pass
        try:
            log_activity(action="delete_schedule_row", details=f"section_id={section_id}")
        except Exception:
            pass
        return jsonify(res), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@schedule_bp.route("/update_schedule_row", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def update_schedule_row():
    """تحديث صف في الجدول الدراسي (للأدمن فقط)."""
    data = request.get_json(force=True) or {}
    section_id = data.get("section_id")
    if not section_id:
        return jsonify({"status": "error", "message": "section_id مطلوب"}), 400
    fields = {}
    for k in ("course_name", "day", "time", "room", "instructor", "semester", "instructor_id"):
        if k in data:
            fields[k] = data.get(k)
    try:
        from backend.core.services import ScheduleService
        res = ScheduleService.update_schedule_row(int(section_id), **fields)
        try:
            with get_connection() as conn:
                touch_schedule_updated_at(conn)
        except Exception:
            pass
        try:
            log_activity(action="update_schedule_row", details=f"section_id={section_id}")
        except Exception:
            pass
        return jsonify(res), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


# -----------------------------
# أدوات إدارية للأوقات/تفريغ الجدول
# -----------------------------
@schedule_bp.route("/distinct_times")
@role_required("admin", "admin_main", "head_of_department")
def distinct_schedule_times():
    """قائمة الأوقات المخزّنة فعلياً في schedule.time (لأغراض التوحيد/التنظيف)."""
    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT DISTINCT COALESCE(time,'') AS time FROM schedule WHERE COALESCE(time,'') <> '' ORDER BY time"
        ).fetchall()
    times = []
    for r in rows or []:
        try:
            times.append((r["time"] if hasattr(r, "keys") else r[0]) or "")
        except Exception:
            pass
    times = [t.strip() for t in times if t and str(t).strip()]
    return jsonify({"status": "ok", "times": times}), 200


@schedule_bp.route("/normalize_times", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def normalize_schedule_times():
    """
    توحيد/تحويل قيم الوقت المخزّنة في schedule.time.
    body:
      mappings: [{from: "09:00-11:00", to: "09:00-12:00"}, ...]
    """
    data = request.get_json(force=True) or {}
    mappings = data.get("mappings") or []
    if not isinstance(mappings, list) or not mappings:
        return jsonify({"status": "error", "message": "mappings مطلوب (قائمة غير فارغة)"}), 400

    normalized = []
    for m in mappings:
        if not isinstance(m, dict):
            continue
        frm = (m.get("from") or "").strip()
        to = (m.get("to") or "").strip()
        if not frm or not to or frm == to:
            continue
        normalized.append((frm, to))
    if not normalized:
        return jsonify({"status": "error", "message": "لا توجد تحويلات صالحة"}), 400

    updated = 0
    with get_connection() as conn:
        cur = conn.cursor()
        for frm, to in normalized:
            cur.execute("UPDATE schedule SET time = ? WHERE time = ?", (to, frm))
            updated += int(cur.rowcount or 0)
        # تفريغ الجداول المشتقة حتى لا تبقى نتائج قديمة
        try:
            cur.execute("DELETE FROM optimized_schedule")
        except Exception:
            pass
        try:
            cur.execute("DELETE FROM conflict_report")
        except Exception:
            pass
        conn.commit()
        try:
            touch_schedule_updated_at(conn)
        except Exception:
            pass

    try:
        log_activity(action="normalize_schedule_times", details=f"mappings={len(normalized)}, updated_rows={updated}")
    except Exception:
        pass

    return jsonify({"status": "ok", "updated_rows": int(updated), "mappings": [{"from": f, "to": t} for f, t in normalized]}), 200


@schedule_bp.route("/clear_all", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def clear_schedule_all():
    """مسح كل صفوف الجدول الدراسي (schedule) مع تفريغ الجداول المشتقة."""
    deleted = 0
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM schedule")
        deleted = int(cur.rowcount or 0)
        try:
            cur.execute("DELETE FROM optimized_schedule")
        except Exception:
            pass
        try:
            cur.execute("DELETE FROM conflict_report")
        except Exception:
            pass
        conn.commit()
        try:
            touch_schedule_updated_at(conn)
        except Exception:
            pass

    try:
        log_activity(action="clear_schedule_all", details=f"deleted_rows={deleted}")
    except Exception:
        pass

    return jsonify({"status": "ok", "deleted_rows": int(deleted)}), 200


@schedule_bp.route("/time_slots")
@login_required
def get_time_slots():
    """جلب تقسيمات الوقت المعتمدة للفصل الحالي (إعداد محفوظ أو افتراضي)."""
    with get_connection() as conn:
        out = _get_time_slots_setting(conn)
    return jsonify({"status": "ok", **out}), 200


@schedule_bp.route("/time_slots", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def save_time_slots():
    """
    حفظ تقسيمات الوقت للفصل الحالي في app_settings.
    body:
      - slots: ["09:00-11:00", ...]
    """
    data = request.get_json(force=True) or {}
    slots = data.get("slots") or []
    if not isinstance(slots, list):
        return jsonify({"status": "error", "message": "slots يجب أن تكون قائمة"}), 400
    cleaned = []
    seen = set()
    for s in slots:
        s = _normalize_time_slot_str(str(s or ""))
        if not s:
            continue
        if not _validate_time_slot_format(s):
            return jsonify({"status": "error", "message": f"صيغة وقت غير صحيحة: {s}"}), 400
        if s in seen:
            continue
        seen.add(s)
        cleaned.append(s)
    if not cleaned:
        return jsonify({"status": "error", "message": "أدخل تقسيمات صالحة (غير فارغة)"}), 400

    actor = (session.get("user") or session.get("username") or "").strip() or "system"
    now = _now_iso_z()
    with get_connection() as conn:
        key = _setting_key_time_slots(conn)
        payload = json.dumps({"slots": cleaned}, ensure_ascii=False)
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
            (key, payload, now, actor),
        )
        conn.commit()
        try:
            log_activity(action="save_time_slots", details=f"key={key}, slots={len(cleaned)}")
        except Exception:
            pass
        out = _get_time_slots_setting(conn)

    return jsonify({"status": "ok", **out}), 200


@schedule_bp.route("/export/pdf")
@role_required("admin", "admin_main", "head_of_department")
def export_schedule_pdf():
    include_empty = str(request.args.get("include_empty") or "").lower() in ("1", "true", "yes")
    official = str(request.args.get("official") or "").lower() in ("1", "true", "yes")
    include_notes = str(request.args.get("include_notes") or "").lower() in ("1", "true", "yes")
    # الافتراضي: التصدير المختصر يكون "رسمي" بدون ملحق/ملاحظات
    if not include_empty and not (official or include_notes):
        official = True
    with get_connection() as conn:
        slots_info = _get_time_slots_setting(conn)
        rows = _load_schedule_rows_for_export(conn)
        built = _build_schedule_triple_export_matrix(rows, slots_info.get("slots") or [], include_empty=include_empty)
        version_info = None
        # إنشاء نسخة تاريخية عند التصدير الرسمي (غير القالب)
        if not include_empty:
            try:
                ev = "export_pdf_official" if official else "export_pdf"
                version_info = _create_schedule_version(conn, event_type=ev, note="schedule pdf export", is_published=False)
            except Exception:
                logger.exception("failed to create schedule version on pdf export")

    cols = built["columns"]
    matrix = built["matrix"]

    def _escape_html(s: str) -> str:
        return (
            str(s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    # جدول التصدير الرسمي بنفس تنسيق العرض الحالي (timetable--cols3)
    timetable_html = (
        "<table class='timetable timetable--cols3'>"
        "<thead>"
        "<tr>"
        "<th rowspan='2' class='day-header'>اليوم</th>"
        + "".join(f"<th colspan='3' class='time-header'>{_escape_html(c)}</th>" for c in cols)
        + "</tr>"
        "<tr>"
        + "".join("<th class='sub-time-header'>المقرر</th><th class='sub-time-header'>الأستاذ</th><th class='sub-time-header'>القاعة</th>" for _ in cols)
        + "</tr>"
        "</thead>"
        "<tbody>"
    )

    for day in matrix.keys():
        timetable_html += f"<tr><th class='day-header'>{_escape_html(day)}</th>"
        for c in cols:
            items = matrix[day].get(c) or []
            timetable_html += "<td colspan='3' class='time-slot-cell slot-slot-block'>"
            timetable_html += "<div class='slot-aligned-rows'>"
            if not items:
                timetable_html += "<div class='slot-course-record slot-course-record--empty'>"
                timetable_html += "<div class='slot-cell slot-cell--course'><span class='slot-placeholder'>—</span></div>"
                timetable_html += "<div class='slot-cell slot-cell--inst'><span class='slot-placeholder'>—</span></div>"
                timetable_html += "<div class='slot-cell slot-cell--room'><span class='slot-placeholder'>—</span></div>"
                timetable_html += "</div>"
            else:
                for idx, it in enumerate(items):
                    if idx > 0:
                        timetable_html += "<div class='slot-record-fullsep'></div>"
                    timetable_html += "<div class='slot-course-record'>"
                    timetable_html += f"<div class='slot-cell slot-cell--course'><span class='course-pub-label'>{_escape_html(it.get('course_name') or '')}</span></div>"
                    timetable_html += f"<div class='slot-cell slot-cell--inst'><span class='slot-text'>{_escape_html(it.get('instructor') or '')}</span></div>"
                    timetable_html += f"<div class='slot-cell slot-cell--room'><span class='slot-text'>{_escape_html(it.get('room') or '')}</span></div>"
                    timetable_html += "</div>"
            timetable_html += "</div></td>"
        timetable_html += "</tr>"
    timetable_html += "</tbody></table>"

    term_label = slots_info.get("term_label") or ""

    appendix_html = ""
    if include_notes and (not official):
        empty_saved = built.get("empty_saved_slots") or []
        nonmatching = built.get("nonmatching_times") or []
        appendix = ""
        if empty_saved:
            appendix += "<p><strong>تقسيمات بدون مقررات:</strong> " + "، ".join(empty_saved) + "</p>"
        if nonmatching:
            appendix += "<p><strong>أوقات موجودة في البيانات لكنها غير ضمن التقسيمات:</strong> " + "، ".join(nonmatching) + "</p>"
        if appendix:
            appendix_html = "<hr/><h3 style='margin:10px 0 6px 0;'>ملحق</h3>" + appendix

    # قالب رسمي أفقي: يملأ الصفحة مع هوامش ضيقة
    now_print = datetime.datetime.now().strftime("%Y-%m-%d")
    signature_block = ""
    if official and not include_empty:
        signature_block = """
        <div class="sign-wrap">
          <div class="sign-name">محمد فرج الحاسي</div>
          <div class="sign-title">رئيس قسم الهندسة الميكانيكية</div>
        </div>
        """

    meta_bits = f"الفصل: {term_label or '—'} <span class=\"sep\">|</span> التاريخ: {now_print}"
    if version_info:
        meta_bits += f" <span class=\"sep\">|</span> النسخة: #{int(version_info.get('version_no') or 0)}"
    if include_empty:
        meta_bits += " <span class=\"sep\">|</span> النوع: قالب"

    logo_src = "/static/images/mech_logo_small.png"
    try:
        logo_file = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "frontend",
            "static",
            "images",
            "mech_logo_small.png",
        )
        with open(os.path.abspath(logo_file), "rb") as lf:
            logo_b64 = base64.b64encode(lf.read()).decode("ascii")
            logo_src = f"data:image/png;base64,{logo_b64}"
    except Exception:
        # fallback to relative static URL if file read fails
        pass

    header_html = f"""
      <div class="hdr official">
        <div class="hdr-col hdr-inst">
          <div class="line">جامعة درنة</div>
          <div class="line">كلية الهندسة</div>
          <div class="line">قسم الهندسة الميكانيكية</div>
        </div>
        <div class="hdr-col hdr-logo">
          <img src="{logo_src}" alt="شعار كلية الهندسة" />
        </div>
        <div class="hdr-col hdr-schedule">
          <div class="line strong">جدول المحاضرات</div>
          <div class="line">فصل {term_label or '—'}</div>
          <div class="line">العام الجامعي 2025 / 2026 م</div>
        </div>
      </div>
      <div class="meta under">{meta_bits}</div>
      <div class="top-rule"></div>
    """

    html = f"""
    <html dir="rtl" lang="ar">
    <head>
      <meta charset="utf-8"/>
      <style>
        /* هوامش ضيقة جداً ومساحة سفلية بسيطة للتوقيع */
        @page {{ size: A4 landscape; margin: 6mm 6mm 12mm 6mm; }}
        body {{ font-family: Arial, sans-serif; padding-bottom: 10mm; color: #111; }}
        /* RTL: العمود الأول يمين الصفحة (الجهة)، الوسط شعار، الأخير يسار (جدول المحاضرات) */
        .hdr.official {{
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
          align-items: start;
          gap: 10px;
          margin-bottom: 1px;
          width: 100%;
          min-height: 95px;
        }}
        .hdr-col {{ line-height: 1.35; font-size: 15px; font-weight: 700; margin-top: 0; padding-top: 0; }}
        .hdr-inst {{ text-align: right; }}
        .hdr-schedule {{ text-align: left; margin-top: 0; padding-top: 0; }}
        .hdr-schedule .line.strong {{ font-size: 17px; }}
        .hdr-logo {{ text-align: center; justify-self: center; margin-top: -2px; }}
        .hdr-logo img {{ width: 82px; height: 82px; object-fit: contain; display: inline-block; vertical-align: top; }}
        .meta {{ color: #444; font-size: 10px; margin-top: 2px; text-align: center; }}
        .meta.under {{ margin-bottom: 1px; }}
        .sep {{ padding: 0 6px; color: #aaa; }}
        .top-rule {{ border-top: 2px solid #000; margin: 1px 0 2px 0; }}
        table.timetable {{ width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; margin-top: 0; border: 1px solid rgba(15,23,42,0.10); border-radius: 8px; }}
        .timetable th, .timetable td {{ border-bottom: 1px solid rgba(15,23,42,0.08); border-left: 1px solid rgba(15,23,42,0.06); padding: 6px 4px; font-size: 9.8px; vertical-align: top; word-wrap: break-word; text-align: center; }}
        .timetable th {{ background: #f8fafc; font-weight: 900; }}
        .timetable th.day-header {{ width: 92px; background: #f1f5f9; }}
        .sub-time-header {{ background: #eef2f7; font-weight: 900; font-size: 9.5px; }}
        .timetable td.time-slot-cell {{ padding: 8px 10px; }}

        .slot-aligned-rows {{ display: flex; flex-direction: column; gap: 0; position: relative; z-index: 2; }}
        .slot-course-record {{ display: grid; grid-template-columns: minmax(0,1.15fr) minmax(0,1fr) minmax(0,0.9fr); gap: 6px 8px; align-items: start; padding: 4px 0; }}
        .slot-course-record--empty {{ opacity: 0.85; }}
        .slot-record-fullsep {{ height: 0; margin: 2px 0 4px; border: 0; border-top: 2px solid rgba(15,23,42,0.16); }}
        .slot-cell {{ min-width: 0; text-align: right; }}
        .slot-text {{ display: block; font-size: 9.8px; font-weight: 700; line-height: 1.25; color: #0f172a; word-break: break-word; }}
        .slot-placeholder {{ color: #94a3b8; font-size: 10px; }}
        .course-pub-label {{ display: block; font-size: 9.8px; font-weight: 700; padding: 3px 4px; border-radius: 6px; background: #e2e8f0; color: #0f172a; line-height: 1.3; }}

        /* الفاصل المطلوب: بين عمود الأستاذ وعمود القاعة */
        .timetable td.slot-slot-block {{ position: relative; }}
        .timetable td.slot-slot-block::after {{
          content: '';
          position: absolute;
          top: 6px;
          bottom: 6px;
          right: 29.5%;
          border-left: 2px solid rgba(15,23,42,0.65);
          pointer-events: none;
          z-index: 1;
        }}
        /* التوقيع أسفل الجدول مباشرة */
        .sign-wrap {{
          margin-top: 6px;
          text-align: center;
          line-height: 1.35;
        }}
        .sign-name {{ font-size: 14px; font-weight: 700; }}
        .sign-title {{ font-size: 16px; font-weight: 800; }}
      </style>
    </head>
    <body>
      {header_html}
      {timetable_html}
      {signature_block}
      {appendix_html}
    </body>
    </html>
    """
    return pdf_response_from_html(html, filename_prefix="schedule")


@schedule_bp.route("/export/excel")
@role_required("admin", "admin_main", "head_of_department")
def export_schedule_excel():
    include_empty = str(request.args.get("include_empty") or "").lower() in ("1", "true", "yes")
    with get_connection() as conn:
        slots_info = _get_time_slots_setting(conn)
        rows = _load_schedule_rows_for_export(conn)
        built = _build_schedule_triple_export_matrix(rows, slots_info.get("slots") or [], include_empty=include_empty)
        if not include_empty:
            try:
                _create_schedule_version(conn, event_type="export_excel", note="schedule excel export", is_published=False)
            except Exception:
                logger.exception("failed to create schedule version on excel export")

    cols = built["columns"]
    matrix = built["matrix"]

    def _join_records(values: list) -> str:
        sep_line = "-----"
        vals = [str(v or "").strip() for v in (values or []) if str(v or "").strip()]
        if not vals:
            return "—"
        return f"\n{sep_line}\n".join(vals)

    # MultiIndex أعمدة: (وقت, مقرر/أستاذ/قاعة)
    multi_cols = [("اليوم", "")]
    for t in cols:
        multi_cols.append((t, "المقرر"))
        multi_cols.append((t, "الأستاذ"))
        multi_cols.append((t, "القاعة"))
    multi_cols = pd.MultiIndex.from_tuples(multi_cols)

    out_rows = []
    for day in matrix.keys():
        row_vals = [day]
        for t in cols:
            items = matrix[day].get(t) or []
            courses = [it.get("course_name") or "" for it in items]
            insts = [it.get("instructor") or "" for it in items]
            rooms = [it.get("room") or "" for it in items]
            row_vals.append(_join_records(courses))
            row_vals.append(_join_records(insts))
            row_vals.append(_join_records(rooms))
        out_rows.append(row_vals)

    # Append notes row
    notes = []
    if built.get("empty_saved_slots"):
        notes.append("تقسيمات بدون مقررات: " + "، ".join(built["empty_saved_slots"]))
    if built.get("nonmatching_times"):
        notes.append("أوقات غير ضمن التقسيمات (موجودة في البيانات): " + "، ".join(built["nonmatching_times"]))
    if notes:
        row_vals = ["ملاحظات"]
        for _ in cols:
            row_vals.extend(["", "", ""])
        if cols:
            row_vals[1] = " | ".join(notes)  # أول (وقت, مقرر)
        out_rows.append(row_vals)

    df = pd.DataFrame(out_rows, columns=multi_cols)
    return excel_response_from_df(df, filename_prefix="schedule")


@schedule_bp.route("/publish_status")
@login_required
def publish_status():
    """حالة نشر الجدول: هل اعتمد الأدمن الجدول ليظهر للطالب والمشرف."""
    with get_connection() as conn:
        published_at = get_schedule_published_at(conn)
    return jsonify({
        "published": published_at is not None,
        "published_at": published_at,
    })


@schedule_bp.route("/publish", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def publish_schedule():
    """اعتماد/نشر الجدول من الأدمن الرئيسي. بعدها يراه الطالب والمشرف وتُستمد منه المقررات المتاحة في خطط التسجيل."""
    try:
        with get_connection() as conn:
            _sync_schedule_pk_col(conn)
            cur = conn.cursor()
            # نسخ الجدول الحالي (schedule) إلى الجدول النهائي (optimized_schedule) لظهوره في صفحة النتائج
            cur.execute("DELETE FROM optimized_schedule")
            cur.execute(f"""
                INSERT INTO optimized_schedule (section_id, course_name, day, time, room, instructor, semester)
                SELECT {SCHEDULE_PK_COL}, course_name, day, time, COALESCE(room,''), COALESCE(instructor,''), COALESCE(semester,'')
                FROM schedule
                WHERE course_name IS NOT NULL AND course_name != '' AND day IS NOT NULL AND day != '' AND time IS NOT NULL AND time != ''
            """)
            conn.commit()
            published_at = set_schedule_published_at(conn)
            # عند النشر، نضبط أيضاً updated_at حتى لا يظهر تحذير فوراً
            try:
                touch_schedule_updated_at(conn)
            except Exception:
                pass
            try:
                recompute_conflict_report(conn)
            except Exception as e:
                logger.exception("فشل إعادة حساب التعارضات عند نشر الجدول: %s", e)
            try:
                ver = _create_schedule_version(conn, event_type="publish", note="schedule published", is_published=True)
            except Exception:
                ver = None
                logger.exception("failed to create schedule version on publish")
        log_activity(action="schedule_publish", details=f"published_at={published_at}")
        out = {"status": "ok", "message": "تم اعتماد ونشر الجدول الدراسي", "published_at": published_at}
        if ver:
            out["version"] = {"id": ver.get("id"), "version_no": ver.get("version_no"), "semester": ver.get("semester")}
        return jsonify(out), 200
    except Exception as e:
        logger.error(f"Error publishing schedule: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@schedule_bp.route("/meta")
@login_required
def schedule_meta():
    """معلومات الجدول المعتمد + آخر تعديل، لعرض تنبيه تغيّر الجدول لجميع الأدوار."""
    with get_connection() as conn:
        published_at = get_schedule_published_at(conn)
        updated_at = get_schedule_updated_at(conn)
    changed_since_publish = False
    if published_at and updated_at:
        # مقارنة نصية ISO بصيغة Z تعمل ترتيبياً
        changed_since_publish = updated_at > published_at
    return jsonify({
        "published": published_at is not None,
        "published_at": published_at,
        "updated_at": updated_at,
        "changed_since_publish": changed_since_publish,
    })


@schedule_bp.route("/versions")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def schedule_versions():
    semester = (request.args.get("semester") or "").strip()
    event_type = (request.args.get("event_type") or "").strip()
    try:
        with get_connection() as conn:
            _sync_schedule_pk_col(conn)
            cur = conn.cursor()
            _ensure_schedule_version_tables(cur)
            where = []
            params = []
            if semester:
                where.append("v.semester = ?")
                params.append(semester)
            if event_type:
                where.append("e.event_type = ?")
                params.append(event_type)
            wsql = ("WHERE " + " AND ".join(where)) if where else ""
            rows = cur.execute(
                f"""
                SELECT v.id, v.semester, v.version_no, v.generated_at, v.generated_by, v.note, v.is_published,
                       e.event_type, e.event_time
                FROM schedule_versions v
                LEFT JOIN schedule_version_events e ON e.schedule_version_id = v.id
                {wsql}
                ORDER BY v.generated_at DESC, v.id DESC
                """,
                params,
            ).fetchall()
            items = []
            for r in rows:
                items.append(
                    {
                        "id": int(r[0]),
                        "semester": r[1] or "",
                        "version_no": int(r[2] or 0),
                        "generated_at": r[3] or "",
                        "generated_by": r[4] or "",
                        "note": r[5] or "",
                        "is_published": bool(int(r[6] or 0)),
                        "event_type": r[7] or "",
                        "event_time": r[8] or "",
                    }
                )
            return jsonify({"status": "ok", "items": items})
    except Exception:
        logger.exception("schedule_versions list failed")
        return jsonify({"status": "error", "message": "فشل تحميل أرشيف نسخ الجدول"}), 500


@schedule_bp.route("/versions/<int:version_id>")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def schedule_version_detail(version_id: int):
    download = str(request.args.get("download") or "").lower() in ("1", "true", "yes")
    format_json = str(request.args.get("format") or "").lower() == "json"
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            _ensure_schedule_version_tables(cur)
            row = cur.execute(
                """
                SELECT id, semester, version_no, snapshot_json, generated_at, generated_by, note, is_published
                FROM schedule_versions
                WHERE id = ?
                LIMIT 1
                """,
                (int(version_id),),
            ).fetchone()
            if not row:
                return jsonify({"status": "error", "message": "النسخة غير موجودة"}), 404
            payload = {
                "id": int(row[0]),
                "semester": row[1] or "",
                "version_no": int(row[2] or 0),
                "generated_at": row[4] or "",
                "generated_by": row[5] or "",
                "note": row[6] or "",
                "is_published": bool(int(row[7] or 0)),
                "snapshot": json.loads(row[3] or "{}"),
            }
            if download or format_json:
                return jsonify(payload)
            snap = payload["snapshot"] if isinstance(payload["snapshot"], dict) else {}
            rows = snap.get("rows") if isinstance(snap.get("rows"), list) else []
            built = _build_schedule_matrix(rows, [], include_empty=False)
            columns = built.get("columns") or []
            matrix = built.get("matrix") or {}
            payload["row_count"] = int(snap.get("row_count") or len(rows))
            return render_template(
                "schedule_version_preview.html",
                item=payload,
                columns=columns,
                matrix=matrix,
            )
    except Exception:
        logger.exception("schedule_version_detail failed")
        return jsonify({"status": "error", "message": "فشل قراءة نسخة الجدول"}), 500


@schedule_bp.route("/versions/<int:version_id>/restore_draft", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def schedule_version_restore_draft(version_id: int):
    """
    استعادة نسخة جدول إلى جدول schedule الحالي كمسودة (بدون نشر).
    لا يغيّر optimized_schedule ولا حالة publish مباشرة.
    """
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            _ensure_schedule_version_tables(cur)
            tname, tyear = get_current_term(conn=conn)
            current_label = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
            row = cur.execute(
                "SELECT semester, version_no, snapshot_json FROM schedule_versions WHERE id = ? LIMIT 1",
                (int(version_id),),
            ).fetchone()
            if not row:
                return jsonify({"status": "error", "message": "النسخة غير موجودة"}), 404

            semester = (row[0] or "").strip()
            if not semester:
                semester = current_label
            if not semester:
                return jsonify({"status": "error", "message": "يجب تحديد الفصل الحالي أولاً من الإعدادات"}), 400
            version_no = int(row[1] or 0)
            try:
                snap = json.loads(row[2] or "{}")
            except Exception:
                snap = {}
            rows = snap.get("rows") if isinstance(snap, dict) else []
            if not isinstance(rows, list):
                rows = []

            # استبدال المسودة الحالية بالكامل بصفوف النسخة
            cur.execute("DELETE FROM schedule")
            restored = 0
            for it in rows:
                if not isinstance(it, dict):
                    continue
                course_name = (it.get("course_name") or "").strip()
                day = (it.get("day") or "").strip()
                time = (it.get("time") or "").strip()
                room = (it.get("room") or "").strip()
                instructor = (it.get("instructor") or "").strip()
                sem = (it.get("semester") or "").strip() or semester
                if not course_name or not day or not time:
                    continue
                cur.execute(
                    """
                    INSERT INTO schedule (course_name, day, time, room, instructor, semester)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (course_name, day, time, room, instructor, sem),
                )
                restored += 1

            try:
                touch_schedule_updated_at(conn)
            except Exception:
                pass

            try:
                _create_schedule_version(
                    conn,
                    event_type="restore_draft",
                    note=f"restored from version_id={int(version_id)} (v{version_no})",
                    is_published=False,
                )
            except Exception:
                logger.exception("failed to log restore_draft version event")
            conn.commit()

        try:
            log_activity(
                action="schedule_restore_draft",
                details=f"version_id={int(version_id)}, version_no={version_no}, restored_rows={restored}",
            )
        except Exception:
            pass

        return jsonify(
            {
                "status": "ok",
                "message": f"تمت استعادة النسخة #{version_no} كمسودة ({restored} صف). يمكنك مراجعتها ثم اعتمادها.",
                "restored_rows": restored,
                "version_no": version_no,
                "semester": semester,
            }
        )
    except Exception:
        logger.exception("schedule_version_restore_draft failed")
        return jsonify({"status": "error", "message": "فشل استعادة النسخة كمسودة"}), 500


@schedule_bp.route("/student_timetable")
@login_required
def student_timetable():
    """
    جدول الطالب الشخصي: يعرض فقط الصفوف المرتبطة بالمقررات المسجل بها.
    الطالب والمشرف يرون الجدول فقط عندما يكون الجدول معتمداً/منشوراً من الأدمن.
    """
    with get_connection() as conn:
        published_at = get_schedule_published_at(conn)
    if published_at is None:
        return jsonify({"rows": [], "published": False})

    user_role = session.get("user_role")
    if user_role == "student":
        sid = session.get("student_id") or session.get("user") or ""
    elif current_supervisor_effective():
        # المشرف يمكنه عرض جدول طلبته المسندين إليه فقط
        sid = (request.args.get("student_id") or "").strip()
        instructor_id = session.get("instructor_id")
        if not instructor_id or not sid:
            return jsonify({"rows": [], "published": True})
        with get_connection() as conn:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT 1 FROM student_supervisor WHERE student_id = ? AND instructor_id = ? LIMIT 1",
                (sid, instructor_id),
            ).fetchone()
            if not row:
                return jsonify({"rows": [], "published": True})
    else:
        sid = (request.args.get("student_id") or "").strip()
    if not sid:
        return jsonify({"rows": [], "published": True})

    with get_connection() as conn:
        _sync_schedule_pk_col(conn)
        cur = conn.cursor()
        q = f"""
        SELECT s.{SCHEDULE_PK_COL} AS section_id,
               s.course_name,
               s.day,
               s.time,
               s.room,
               s.instructor,
               s.semester
        FROM schedule s
        JOIN registrations r ON r.course_name = s.course_name
        WHERE r.student_id = ?
        ORDER BY s.day, s.time, s.course_name
        """
        rows = cur.execute(q, (sid,)).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "section_id": r[0],
                    "course_name": r[1],
                    "day": r[2],
                    "time": r[3],
                    "room": r[4],
                    "instructor": r[5],
                    "semester": r[6],
                }
            )
    return jsonify({"rows": out, "published": True})


def _canonical_schedule_day_label(day: str | None) -> str:
    """توحيد تهجئة اليوم مع واجهة الجدول (مثلاً الاثنين → الإثنين)."""
    s = (day or "").strip()
    if not s:
        return s
    aliases = {
        "الاثنين": "الإثنين",
        "إثنين": "الإثنين",
        "الثلاثا": "الثلاثاء",
        "الاربعاء": "الأربعاء",
        "الأربعا": "الأربعاء",
        "اربعاء": "الأربعاء",
    }
    return aliases.get(s, s)


def _assigned_section_rows(cur, instructor_db_id: int, canonical_instructor_name: str):
    """
    صفوف schedule المكلَّف بها الأستاذ:
    - تطابق مباشر على schedule.instructor_id عند تعبئته من الإدارة؛
    - أو مطابقة الاسم النصّي بعد تطبيع الفراغات (الترقية من الجداول القديمة).
    """
    _sync_schedule_pk_col(cur.connection)
    norm = normalize_instructor_name(canonical_instructor_name)
    q = f"""
        SELECT s.{SCHEDULE_PK_COL} AS section_id,
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
    out = []
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
        if (iid_int is None or iid_int == 0) and normalize_instructor_name(inst_txt) == norm:
            out.append((sid, cn, day, tim, room, inst_txt, sem))
    return out


def _axis_status_map_for_sections(cur, instructor_db_id: int, section_ids: list) -> dict:
    """خريطة section_id -> {axis_key: status}."""
    if not section_ids:
        return {}
    placeholders = ",".join(["?"] * len(section_ids))
    q = f"""
        SELECT section_id, axis_key, status
        FROM faculty_section_axis_status
        WHERE instructor_id = ? AND section_id IN ({placeholders})
    """
    rows = cur.execute(q, (instructor_db_id, *section_ids)).fetchall()
    m: dict = {int(sid): {} for sid in section_ids}
    for sid, ax, st in rows:
        m.setdefault(int(sid), {})[ax] = st
    return m


def _course_admin_payload(cur, instructor_id: int, section_id: int) -> dict:
    """تحميل بيانات إدارة المقرر (الخطة الأسبوعية + الإعلانات + المفردات) لشعبة واحدة."""
    plan_rows = cur.execute(
        """
        SELECT week_no, COALESCE(week_topic,''), COALESCE(lecture_status,'planned'), COALESCE(resources_text,'')
        FROM faculty_course_plans
        WHERE section_id = ? AND instructor_id = ?
        ORDER BY week_no
        """,
        (section_id, instructor_id),
    ).fetchall()
    ann_rows = cur.execute(
        """
        SELECT id, COALESCE(title,''), COALESCE(body,''), COALESCE(announcement_type,'general'),
               COALESCE(lecture_date,''), COALESCE(published_to_students,1), COALESCE(created_at,'')
        FROM faculty_course_announcements
        WHERE section_id = ? AND instructor_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (section_id, instructor_id),
    ).fetchall()
    syl_row = cur.execute(
        """
        SELECT COALESCE(syllabus_text,'')
        FROM faculty_course_syllabi
        WHERE section_id = ? AND instructor_id = ?
        LIMIT 1
        """,
        (section_id, instructor_id),
    ).fetchone()
    closure_row = cur.execute(
        """
        SELECT id, COALESCE(implementation_summary,''), COALESCE(improvement_notes,''),
               COALESCE(reflection_text,''), COALESCE(status,'draft'), COALESCE(updated_at,'')
        FROM course_closure_reports
        WHERE section_id = ? AND instructor_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (section_id, instructor_id),
    ).fetchone()
    return {
        "weekly_plan": [
            {
                "week_no": int(r[0] or 0),
                "week_topic": r[1] or "",
                "lecture_status": r[2] or "planned",
                "resources_text": r[3] or "",
            }
            for r in (plan_rows or [])
        ],
        "announcements": [
            {
                "id": int(r[0]),
                "title": r[1] or "",
                "body": r[2] or "",
                "announcement_type": r[3] or "general",
                "lecture_date": r[4] or "",
                "published_to_students": bool(int(r[5] or 0)),
                "created_at": r[6] or "",
            }
            for r in (ann_rows or [])
        ],
        "syllabus_text": (syl_row[0] if syl_row else "") or "",
        "closure_report": {
            "id": (int(closure_row[0]) if closure_row else None),
            "implementation_summary": (closure_row[1] if closure_row else "") or "",
            "improvement_notes": (closure_row[2] if closure_row else "") or "",
            "reflection_text": (closure_row[3] if closure_row else "") or "",
            "status": (closure_row[4] if closure_row else "draft") or "draft",
            "updated_at": (closure_row[5] if closure_row else "") or "",
        },
    }


def _instructor_display_name_for_session() -> tuple[str | None, int | None]:
    """
    اسم العرض المطابق لحقل schedule.instructor من جدول instructors، ومعرف السجل.
    يُستخدم لربط حساب المستخدم (instructor_id) بالصفوف المكلَّف بها في الجدول.
    """
    if not _is_instructor_effective_session():
        return None, None
    instructor_id = session.get("instructor_id")
    if not instructor_id:
        return None, None
    try:
        iid = int(instructor_id)
    except (TypeError, ValueError):
        return None, None
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT COALESCE(TRIM(name), '') FROM instructors WHERE id = ? LIMIT 1",
            (iid,),
        ).fetchone()
    name = (row[0] if row else "") or ""
    if not name.strip():
        return None, iid
    return normalize_instructor_name(name), iid


def _is_privileged_assignment_viewer() -> bool:
    role = (session.get("user_role") or "").strip()
    return role in ("admin", "admin_main", "head_of_department")


def _is_instructor_effective_session() -> bool:
    """وضع التدريس الفعّال: instructor أو رئيس قسم عندما active_mode=instructor."""
    role = (session.get("user_role") or "").strip()
    if role == "instructor":
        return True
    if role == "head_of_department":
        mode = (session.get("active_mode") or "head").strip().lower()
        return mode == "instructor"
    return False


def _can_access_assignment(instructor_id: int) -> bool:
    if _is_privileged_assignment_viewer():
        return True
    if not _is_instructor_effective_session():
        return False
    try:
        sid = int(session.get("instructor_id") or 0)
    except (TypeError, ValueError):
        return False
    return sid == int(instructor_id)


@schedule_bp.route("/my_assigned_sections")
@login_required
def my_assigned_sections():
    """
    الشعب/الصفوف في الجدول الدراسي المكلَّف بها الأستاذ (حسب تطابق الاسم مع schedule.instructor).
    لا يشترط نشر الجدول — يظهر التكليف كما أعدّه رئيس القسم/الإدارة في الجدول الحالي.
    """
    if not _is_instructor_effective_session():
        return jsonify({"status": "error", "message": "غير مصرح"}), 403

    inst_name, instructor_id = _instructor_display_name_for_session()
    published_at = None
    with get_connection() as conn:
        published_at = get_schedule_published_at(conn)

    if not inst_name:
        return jsonify(
            {
                "rows": [],
                "instructor_name": None,
                "instructor_id": instructor_id,
                "schedule_published": published_at is not None,
                "axis_catalog": axis_labels_for_api(),
                "hint": "لا يوجد ربط باسم في دليل هيئة التدريس — راجع المسؤول لربط الحساب بسجل عضو هيئة التدريس.",
            }
        )

    iid = int(instructor_id)
    default_axes = {k: "pending" for k in FACULTY_AXIS_KEYS}
    with get_connection() as conn:
        cur = conn.cursor()
        tuples = _assigned_section_rows(cur, iid, inst_name)
        section_ids = [t[0] for t in tuples]
        axis_map = _axis_status_map_for_sections(cur, iid, section_ids)
        out = []
        for t in tuples:
            sid, cn, day, tim, room, inst_txt, sem = t
            merged_axes = {**default_axes, **axis_map.get(int(sid), {})}
            out.append(
                {
                    "section_id": sid,
                    "course_name": cn,
                    "day": day,
                    "time": tim,
                    "room": room,
                    "instructor": inst_txt,
                    "semester": sem,
                    "axes": merged_axes,
                }
            )
    return jsonify(
        {
            "rows": out,
            "instructor_name": inst_name,
            "instructor_id": instructor_id,
            "schedule_published": published_at is not None,
            "axis_catalog": axis_labels_for_api(),
        }
    )


@schedule_bp.route("/faculty_assignments", methods=["GET"])
@login_required
def list_faculty_assignments():
    role = (session.get("user_role") or "").strip()
    if role not in ("admin", "admin_main", "head_of_department", "instructor"):
        return jsonify({"status": "error", "message": "غير مصرح"}), 403

    requested_instructor_id = request.args.get("instructor_id", type=int)
    include_inactive = int(request.args.get("include_inactive", type=int) or 0) == 1
    if _is_privileged_assignment_viewer():
        effective_instructor_id = requested_instructor_id
    else:
        effective_instructor_id = int(session.get("instructor_id") or 0) or None
        if requested_instructor_id and requested_instructor_id != effective_instructor_id:
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

    with get_connection() as conn:
        cur = conn.cursor()
        params = []
        q = """
            SELECT a.id,
                   a.instructor_id,
                   COALESCE(i.name,'') AS instructor_name,
                   COALESCE(a.assignment_type,'') AS assignment_type,
                   a.section_id,
                   COALESCE(a.title,'') AS title,
                   COALESCE(a.decision_ref,'') AS decision_ref,
                   COALESCE(a.assignment_date,'') AS assignment_date,
                   COALESCE(a.start_date,'') AS start_date,
                   COALESCE(a.end_date,'') AS end_date,
                   COALESCE(a.is_active,1) AS is_active
            FROM faculty_assignments a
            LEFT JOIN instructors i ON i.id = a.instructor_id
            WHERE 1=1
        """
        if effective_instructor_id:
            q += " AND a.instructor_id = ?"
            params.append(int(effective_instructor_id))
        if not include_inactive:
            q += " AND COALESCE(a.is_active,1) = 1"
        q += " ORDER BY a.assignment_date DESC, a.id DESC"
        rows = cur.execute(q, tuple(params)).fetchall()

    out = []
    for r in rows or []:
        out.append(
            {
                "id": int(r[0]),
                "instructor_id": int(r[1]),
                "instructor_name": r[2] or "",
                "assignment_type": r[3] or "",
                "section_id": (int(r[4]) if r[4] not in (None, "") else None),
                "title": r[5] or "",
                "decision_ref": r[6] or "",
                "assignment_date": r[7] or "",
                "start_date": r[8] or "",
                "end_date": r[9] or "",
                "is_active": bool(int(r[10] or 0)),
            }
        )
    return jsonify({"status": "ok", "items": out})


@schedule_bp.route("/faculty_assignments", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def create_faculty_assignment():
    data = request.get_json(force=True) or {}
    instructor_id = data.get("instructor_id")
    assignment_type = (data.get("assignment_type") or "").strip().lower()
    title = (data.get("title") or "").strip()
    decision_ref = (data.get("decision_ref") or "").strip()
    assignment_date = (data.get("assignment_date") or "").strip()
    start_date = (data.get("start_date") or "").strip()
    end_date = (data.get("end_date") or "").strip()
    section_id_raw = data.get("section_id")

    try:
        instructor_id = int(instructor_id)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "instructor_id غير صالح"}), 400
    if assignment_type not in VALID_FACULTY_ASSIGNMENT_TYPES:
        return jsonify({"status": "error", "message": "assignment_type غير صالح"}), 400
    if not title:
        return jsonify({"status": "error", "message": "title مطلوب"}), 400
    if not decision_ref:
        return jsonify({"status": "error", "message": "decision_ref مطلوب"}), 400
    section_id = None
    if section_id_raw not in (None, ""):
        try:
            section_id = int(section_id_raw)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "section_id غير صالح"}), 400

    actor = (session.get("user") or session.get("username") or "").strip() or "system"
    now = datetime.datetime.utcnow().isoformat()
    assignment_date = assignment_date or now
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM instructors WHERE id = ? LIMIT 1", (instructor_id,))
        if not cur.fetchone():
            return jsonify({"status": "error", "message": "instructor_id غير موجود"}), 400
        if is_postgresql():
            row_new = cur.execute(
                """
                INSERT INTO faculty_assignments
                    (instructor_id, assignment_type, section_id, title, decision_ref, assignment_date, start_date, end_date, is_active, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                RETURNING id
                """,
                (instructor_id, assignment_type, section_id, title, decision_ref, assignment_date, start_date, end_date, now, actor),
            ).fetchone()
            aid = int(row_new[0]) if row_new else 0
        else:
            cur.execute(
                """
                INSERT INTO faculty_assignments
                    (instructor_id, assignment_type, section_id, title, decision_ref, assignment_date, start_date, end_date, is_active, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (instructor_id, assignment_type, section_id, title, decision_ref, assignment_date, start_date, end_date, now, actor),
            )
            aid = int(cur.lastrowid or 0)
        conn.commit()
    return jsonify({"status": "ok", "assignment_id": aid}), 200


@schedule_bp.route("/faculty_assignment_logs", methods=["GET"])
@login_required
def list_faculty_assignment_logs():
    role = (session.get("user_role") or "").strip()
    if role not in ("admin", "admin_main", "head_of_department", "instructor"):
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    assignment_id = request.args.get("assignment_id", type=int)
    if not assignment_id:
        return jsonify({"status": "error", "message": "assignment_id مطلوب"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT instructor_id FROM faculty_assignments WHERE id = ? LIMIT 1",
            (int(assignment_id),),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "assignment not found"}), 404
        assignment_instructor = int(row[0])
        if not _can_access_assignment(assignment_instructor):
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

        rows = cur.execute(
            """
            SELECT id, assignment_id, instructor_id, section_id, log_type, notes, created_at, created_by,
                   approval_status, approved_at, approved_by
            FROM faculty_assignment_logs
            WHERE assignment_id = ?
            ORDER BY id DESC
            """,
            (int(assignment_id),),
        ).fetchall()
    out = []
    for r in rows or []:
        out.append(
            {
                "id": int(r[0]),
                "assignment_id": int(r[1]),
                "instructor_id": int(r[2]),
                "section_id": (int(r[3]) if r[3] not in (None, "") else None),
                "log_type": r[4] or "",
                "notes": r[5] or "",
                "created_at": r[6] or "",
                "created_by": r[7] or "",
                "approval_status": r[8] or "draft",
                "approved_at": r[9] or "",
                "approved_by": r[10] or "",
            }
        )
    return jsonify({"status": "ok", "items": out})


@schedule_bp.route("/faculty_assignment_logs", methods=["POST"])
@login_required
def create_faculty_assignment_log():
    role = (session.get("user_role") or "").strip()
    if role not in ("admin", "admin_main", "head_of_department", "instructor"):
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    data = request.get_json(force=True) or {}
    assignment_id = data.get("assignment_id")
    log_type = (data.get("log_type") or "").strip().lower()
    notes = (data.get("notes") or "").strip()
    approval_status = (data.get("approval_status") or "draft").strip().lower()

    try:
        assignment_id = int(assignment_id)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "assignment_id غير صالح"}), 400
    if log_type not in VALID_FACULTY_LOG_TYPES:
        return jsonify({"status": "error", "message": "log_type غير صالح"}), 400
    if approval_status not in VALID_FACULTY_LOG_APPROVAL:
        return jsonify({"status": "error", "message": "approval_status غير صالح"}), 400
    if not notes:
        return jsonify({"status": "error", "message": "notes مطلوبة"}), 400

    actor = (session.get("user") or session.get("username") or "").strip() or "system"
    now = datetime.datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, instructor_id, section_id FROM faculty_assignments WHERE id = ? LIMIT 1",
            (assignment_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "assignment not found"}), 404
        assignment_instructor_id = int(row[1])
        section_id = row[2]
        if not _can_access_assignment(assignment_instructor_id):
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        if role == "instructor" and approval_status in ("approved", "rejected"):
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

        approved_at = now if approval_status in ("approved", "rejected") else None
        approved_by = actor if approval_status in ("approved", "rejected") else None
        if is_postgresql():
            row_new = cur.execute(
                """
                INSERT INTO faculty_assignment_logs
                    (assignment_id, instructor_id, section_id, log_type, notes, created_at, created_by, approval_status, approved_at, approved_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    assignment_id,
                    assignment_instructor_id,
                    section_id,
                    log_type,
                    notes,
                    now,
                    actor,
                    approval_status,
                    approved_at,
                    approved_by,
                ),
            ).fetchone()
            lid = int(row_new[0]) if row_new else 0
        else:
            cur.execute(
                """
                INSERT INTO faculty_assignment_logs
                    (assignment_id, instructor_id, section_id, log_type, notes, created_at, created_by, approval_status, approved_at, approved_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assignment_id,
                    assignment_instructor_id,
                    section_id,
                    log_type,
                    notes,
                    now,
                    actor,
                    approval_status,
                    approved_at,
                    approved_by,
                ),
            )
            lid = int(cur.lastrowid or 0)
        conn.commit()
    return jsonify({"status": "ok", "log_id": lid}), 200


@schedule_bp.route("/my_axis_status", methods=["POST"])
@login_required
def save_my_axis_status():
    """تحديث حالة محور واحد لشعبة مكلَّف بها الأستاذ."""
    if not _is_instructor_effective_session():
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    data = request.get_json(force=True) or {}
    try:
        section_id = int(data.get("section_id"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "section_id غير صالح"}), 400
    axis_key = (data.get("axis_key") or "").strip()
    status = (data.get("status") or "pending").strip()
    if axis_key not in FACULTY_AXIS_KEYS or status not in VALID_AXIS_STATUS:
        return jsonify({"status": "error", "message": "axis_key أو status غير صالح"}), 400

    inst_name, instructor_id = _instructor_display_name_for_session()
    if not instructor_id:
        return jsonify({"status": "error", "message": "لا يوجد ربط بعضو هيئة التدريس"}), 400
    iid = int(instructor_id)

    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        cur = conn.cursor()
        term_label = _current_term_label_safe(conn)
        if _is_faculty_cycle_locked(conn, term_label):
            return jsonify({"status": "error", "message": "تم إغلاق دورة الفصل الحالي للتعديل"}), 423
        tuples = _assigned_section_rows(cur, iid, inst_name or "")
        allowed_ids = {int(t[0]) for t in tuples}
        if section_id not in allowed_ids:
            return jsonify({"status": "error", "message": "هذه الشعبة غير مكلَّفة لحسابك"}), 403
        if status == "done" and not _has_section_evidence(cur, section_id, iid):
            return jsonify({"status": "error", "message": "لا يمكن إنهاء المحور دون وجود دليل تنفيذ فعلي للشعبة"}), 400

        cur.execute(
            """
            INSERT INTO faculty_section_axis_status (section_id, instructor_id, axis_key, status, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (section_id, instructor_id, axis_key)
            DO UPDATE SET status = EXCLUDED.status, updated_at = EXCLUDED.updated_at
            """,
            (section_id, iid, axis_key, status, ts),
        )
        conn.commit()
    return jsonify({"status": "ok", "section_id": section_id, "axis_key": axis_key, "saved": status})


@schedule_bp.route("/my_course_admin")
@login_required
def my_course_admin():
    """تفاصيل إدارة المقرر لشعبة مكلّف بها الأستاذ."""
    if not _is_instructor_effective_session():
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    try:
        section_id = int((request.args.get("section_id") or "").strip())
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "section_id غير صالح"}), 400

    inst_name, instructor_id = _instructor_display_name_for_session()
    if not instructor_id:
        return jsonify({"status": "error", "message": "لا يوجد ربط بعضو هيئة التدريس"}), 400
    iid = int(instructor_id)
    with get_connection() as conn:
        cur = conn.cursor()
        tuples = _assigned_section_rows(cur, iid, inst_name or "")
        allowed_ids = {int(t[0]) for t in tuples}
        if section_id not in allowed_ids:
            return jsonify({"status": "error", "message": "هذه الشعبة غير مكلَّفة لحسابك"}), 403
        payload = _course_admin_payload(cur, iid, section_id)
    return jsonify({"status": "ok", "section_id": section_id, **payload})


@schedule_bp.route("/my_course_plan", methods=["POST"])
@login_required
def save_my_course_plan():
    """حفظ أو تحديث عنصر في الخطة الأسبوعية لشعبة مكلّف بها الأستاذ."""
    if not _is_instructor_effective_session():
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    data = request.get_json(force=True) or {}
    try:
        section_id = int(data.get("section_id"))
        week_no = int(data.get("week_no"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "section_id/week_no غير صالح"}), 400
    if week_no < 1 or week_no > 52:
        return jsonify({"status": "error", "message": "week_no يجب أن يكون بين 1 و 52"}), 400
    lecture_status = (data.get("lecture_status") or "planned").strip()
    if lecture_status not in VALID_LECTURE_STATUS:
        return jsonify({"status": "error", "message": "lecture_status غير صالح"}), 400
    week_topic = (data.get("week_topic") or "").strip()
    resources_text = (data.get("resources_text") or "").strip()

    inst_name, instructor_id = _instructor_display_name_for_session()
    if not instructor_id:
        return jsonify({"status": "error", "message": "لا يوجد ربط بعضو هيئة التدريس"}), 400
    iid = int(instructor_id)
    actor = (session.get("user") or "").strip()
    ts = datetime.datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        term_label = _current_term_label_safe(conn)
        if _is_faculty_cycle_locked(conn, term_label):
            return jsonify({"status": "error", "message": "تم إغلاق دورة الفصل الحالي للتعديل"}), 423
        tuples = _assigned_section_rows(cur, iid, inst_name or "")
        allowed_ids = {int(t[0]) for t in tuples}
        if section_id not in allowed_ids:
            return jsonify({"status": "error", "message": "هذه الشعبة غير مكلَّفة لحسابك"}), 403
        cur.execute(
            """
            INSERT INTO faculty_course_plans
                (section_id, instructor_id, week_no, week_topic, lecture_status, resources_text, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (section_id, instructor_id, week_no)
            DO UPDATE SET week_topic = EXCLUDED.week_topic,
                          lecture_status = EXCLUDED.lecture_status,
                          resources_text = EXCLUDED.resources_text,
                          updated_at = EXCLUDED.updated_at,
                          updated_by = EXCLUDED.updated_by
            """,
            (section_id, iid, week_no, week_topic, lecture_status, resources_text, ts, actor),
        )
        conn.commit()
        payload = _course_admin_payload(cur, iid, section_id)
    return jsonify({"status": "ok", "section_id": section_id, **payload})


def _delete_my_course_plan_impl(data: dict):
    """تنفيذ حذف عنصر من الخطة الأسبوعية لشعبة مكلّف بها الأستاذ."""
    if not _is_instructor_effective_session():
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    try:
        section_id = int(data.get("section_id"))
        week_no = int(data.get("week_no"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "section_id/week_no غير صالح"}), 400
    if week_no < 1 or week_no > 52:
        return jsonify({"status": "error", "message": "week_no يجب أن يكون بين 1 و 52"}), 400

    inst_name, instructor_id = _instructor_display_name_for_session()
    if not instructor_id:
        return jsonify({"status": "error", "message": "لا يوجد ربط بعضو هيئة التدريس"}), 400
    iid = int(instructor_id)
    with get_connection() as conn:
        cur = conn.cursor()
        term_label = _current_term_label_safe(conn)
        if _is_faculty_cycle_locked(conn, term_label):
            return jsonify({"status": "error", "message": "تم إغلاق دورة الفصل الحالي للتعديل"}), 423
        tuples = _assigned_section_rows(cur, iid, inst_name or "")
        allowed_ids = {int(t[0]) for t in tuples}
        if section_id not in allowed_ids:
            return jsonify({"status": "error", "message": "هذه الشعبة غير مكلَّفة لحسابك"}), 403
        cur.execute(
            """
            DELETE FROM faculty_course_plans
            WHERE section_id = ? AND instructor_id = ? AND week_no = ?
            """,
            (section_id, iid, week_no),
        )
        deleted = int(cur.rowcount or 0)
        conn.commit()
        payload = _course_admin_payload(cur, iid, section_id)
    return jsonify({"status": "ok", "section_id": section_id, "deleted": deleted, **payload})


@schedule_bp.route("/my_course_plan", methods=["DELETE"])
@login_required
def delete_my_course_plan():
    data = request.get_json(force=True) or {}
    return _delete_my_course_plan_impl(data)


@schedule_bp.route("/my_course_plan/delete", methods=["POST"])
@login_required
def delete_my_course_plan_post():
    """مسار بديل لحذف أسبوع من الخطة (للتوافق مع بيئات لا تدعم DELETE جيدًا)."""
    data = request.get_json(force=True) or {}
    return _delete_my_course_plan_impl(data)


@schedule_bp.route("/my_course_syllabus", methods=["POST"])
@login_required
def save_my_course_syllabus():
    """حفظ مفردات المقرر (syllabus) لشعبة مكلّف بها الأستاذ."""
    if not _is_instructor_effective_session():
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    data = request.get_json(force=True) or {}
    try:
        section_id = int(data.get("section_id"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "section_id غير صالح"}), 400
    syllabus_text = (data.get("syllabus_text") or "").strip()
    inst_name, instructor_id = _instructor_display_name_for_session()
    if not instructor_id:
        return jsonify({"status": "error", "message": "لا يوجد ربط بعضو هيئة التدريس"}), 400
    iid = int(instructor_id)
    actor = (session.get("user") or "").strip()
    ts = datetime.datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        term_label = _current_term_label_safe(conn)
        if _is_faculty_cycle_locked(conn, term_label):
            return jsonify({"status": "error", "message": "تم إغلاق دورة الفصل الحالي للتعديل"}), 423
        tuples = _assigned_section_rows(cur, iid, inst_name or "")
        allowed_ids = {int(t[0]) for t in tuples}
        if section_id not in allowed_ids:
            return jsonify({"status": "error", "message": "هذه الشعبة غير مكلَّفة لحسابك"}), 403
        cur.execute(
            """
            INSERT INTO faculty_course_syllabi (section_id, instructor_id, syllabus_text, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (section_id, instructor_id)
            DO UPDATE SET syllabus_text = EXCLUDED.syllabus_text,
                          updated_at = EXCLUDED.updated_at,
                          updated_by = EXCLUDED.updated_by
            """,
            (section_id, iid, syllabus_text, ts, actor),
        )
        conn.commit()
        payload = _course_admin_payload(cur, iid, section_id)
    return jsonify({"status": "ok", "section_id": section_id, **payload})


@schedule_bp.route("/my_course_announcement", methods=["POST"])
@login_required
def save_my_course_announcement():
    """إضافة إعلان لشعبة مكلّف بها الأستاذ."""
    if not _is_instructor_effective_session():
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    data = request.get_json(force=True) or {}
    try:
        section_id = int(data.get("section_id"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "section_id غير صالح"}), 400
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"status": "error", "message": "نص الإعلان مطلوب"}), 400
    title = (data.get("title") or "").strip()
    announcement_type = (data.get("announcement_type") or "general").strip()
    if announcement_type not in VALID_ANNOUNCEMENT_TYPES:
        return jsonify({"status": "error", "message": "نوع الإعلان غير صالح"}), 400
    lecture_date = (data.get("lecture_date") or "").strip()
    published_to_students = 1 if bool(data.get("published_to_students", True)) else 0

    inst_name, instructor_id = _instructor_display_name_for_session()
    if not instructor_id:
        return jsonify({"status": "error", "message": "لا يوجد ربط بعضو هيئة التدريس"}), 400
    iid = int(instructor_id)
    actor = (session.get("user") or "").strip()
    with get_connection() as conn:
        cur = conn.cursor()
        term_label = _current_term_label_safe(conn)
        if _is_faculty_cycle_locked(conn, term_label):
            return jsonify({"status": "error", "message": "تم إغلاق دورة الفصل الحالي للتعديل"}), 423
        tuples = _assigned_section_rows(cur, iid, inst_name or "")
        allowed_ids = {int(t[0]) for t in tuples}
        if section_id not in allowed_ids:
            return jsonify({"status": "error", "message": "هذه الشعبة غير مكلَّفة لحسابك"}), 403
        cur.execute(
            """
            INSERT INTO faculty_course_announcements
                (section_id, instructor_id, title, body, announcement_type, lecture_date, published_to_students, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (section_id, iid, title, body, announcement_type, lecture_date, published_to_students, actor),
        )
        conn.commit()
        payload = _course_admin_payload(cur, iid, section_id)
    return jsonify({"status": "ok", "section_id": section_id, **payload})


@schedule_bp.route("/my_course_closure", methods=["POST"])
@login_required
def save_my_course_closure():
    """حفظ/إرسال تقرير إقفال المقرر لشعبة مكلّف بها الأستاذ."""
    if not _is_instructor_effective_session():
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    data = request.get_json(force=True) or {}
    try:
        section_id = int(data.get("section_id"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "section_id غير صالح"}), 400
    status = (data.get("status") or "draft").strip().lower()
    if status not in ("draft", "submitted"):
        return jsonify({"status": "error", "message": "status غير صالح"}), 400
    implementation_summary = (data.get("implementation_summary") or "").strip()
    improvement_notes = (data.get("improvement_notes") or "").strip()
    reflection_text = (data.get("reflection_text") or "").strip()

    inst_name, instructor_id = _instructor_display_name_for_session()
    if not instructor_id:
        return jsonify({"status": "error", "message": "لا يوجد ربط بعضو هيئة التدريس"}), 400
    iid = int(instructor_id)
    actor = (session.get("user") or "").strip()
    now = datetime.datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        term_label = _current_term_label_safe(conn)
        if _is_faculty_cycle_locked(conn, term_label):
            return jsonify({"status": "error", "message": "تم إغلاق دورة الفصل الحالي للتعديل"}), 423
        tuples = _assigned_section_rows(cur, iid, inst_name or "")
        allowed_ids = {int(t[0]) for t in tuples}
        if section_id not in allowed_ids:
            return jsonify({"status": "error", "message": "هذه الشعبة غير مكلَّفة لحسابك"}), 403
        sem_row = next((t for t in tuples if int(t[0]) == section_id), None)
        semester = (sem_row[6] if sem_row else "") or "UNKNOWN_TERM"
        if is_postgresql():
            cur.execute(
                """
                INSERT INTO course_closure_reports
                    (section_id, instructor_id, semester, implementation_summary, improvement_notes, reflection_text,
                     status, created_at, created_by, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (section_id, instructor_id, semester)
                DO UPDATE SET implementation_summary = EXCLUDED.implementation_summary,
                              improvement_notes = EXCLUDED.improvement_notes,
                              reflection_text = EXCLUDED.reflection_text,
                              status = EXCLUDED.status,
                              updated_at = EXCLUDED.updated_at,
                              updated_by = EXCLUDED.updated_by
                """,
                (section_id, iid, semester, implementation_summary, improvement_notes, reflection_text, status, now, actor, now, actor),
            )
        else:
            row = cur.execute(
                "SELECT id FROM course_closure_reports WHERE section_id=? AND instructor_id=? AND semester=? LIMIT 1",
                (section_id, iid, semester),
            ).fetchone()
            if row:
                cur.execute(
                    """
                    UPDATE course_closure_reports
                    SET implementation_summary=?, improvement_notes=?, reflection_text=?, status=?, updated_at=?, updated_by=?
                    WHERE id=?
                    """,
                    (implementation_summary, improvement_notes, reflection_text, status, now, actor, int(row[0])),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO course_closure_reports
                        (section_id, instructor_id, semester, implementation_summary, improvement_notes, reflection_text,
                         status, created_at, created_by, updated_at, updated_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (section_id, iid, semester, implementation_summary, improvement_notes, reflection_text, status, now, actor, now, actor),
                )
        conn.commit()
        payload = _course_admin_payload(cur, iid, section_id)
    return jsonify({"status": "ok", "section_id": section_id, **payload})


@schedule_bp.route("/course_closure_reports", methods=["GET"])
@role_required("admin", "admin_main", "head_of_department")
def list_course_closure_reports():
    status = (request.args.get("status") or "").strip().lower()
    with get_connection() as conn:
        _sync_schedule_pk_col(conn)
        cur = conn.cursor()
        q = f"""
            SELECT c.id, c.section_id, c.instructor_id, COALESCE(i.name,'') AS instructor_name,
                   COALESCE(s.course_name,'') AS course_name, COALESCE(c.semester,'') AS semester,
                   COALESCE(c.implementation_summary,'') AS implementation_summary,
                   COALESCE(c.improvement_notes,'') AS improvement_notes,
                   COALESCE(c.reflection_text,'') AS reflection_text,
                   COALESCE(c.status,'draft') AS status,
                   COALESCE(c.updated_at,'') AS updated_at,
                   COALESCE(c.approved_at,'') AS approved_at,
                   COALESCE(c.approved_by,'') AS approved_by
            FROM course_closure_reports c
            LEFT JOIN instructors i ON i.id = c.instructor_id
            LEFT JOIN schedule s ON s.{SCHEDULE_PK_COL} = c.section_id
            WHERE 1=1
        """
        params = []
        if status in ("draft", "submitted", "approved", "rejected"):
            q += " AND c.status = ?"
            params.append(status)
        q += " ORDER BY c.updated_at DESC, c.id DESC"
        rows = cur.execute(q, tuple(params)).fetchall()
    items = [dict(r) for r in (rows or [])]
    return jsonify({"status": "ok", "items": items})


@schedule_bp.route("/course_closure_reports/<int:report_id>/review", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def review_course_closure_report(report_id: int):
    data = request.get_json(force=True) or {}
    status = (data.get("status") or "").strip().lower()
    if status not in ("approved", "rejected"):
        return jsonify({"status": "error", "message": "status غير صالح"}), 400
    review_note = (data.get("review_note") or "").strip()
    actor = (session.get("user") or "").strip() or "system"
    now = datetime.datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute("SELECT id FROM course_closure_reports WHERE id = ? LIMIT 1", (int(report_id),)).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "report not found"}), 404
        cur.execute(
            """
            UPDATE course_closure_reports
            SET status = ?, review_note = ?, approved_at = ?, approved_by = ?, updated_at = ?, updated_by = ?
            WHERE id = ?
            """,
            (status, review_note, now, actor, now, actor, int(report_id)),
        )
        _append_governance_audit(
            conn=conn,
            actor=actor,
            action="COURSE_CLOSURE_REVIEW",
            scope_type="course_closure_report",
            scope_id=str(int(report_id)),
            old_value="submitted",
            new_value=status,
            reason=review_note,
        )
        conn.commit()
    return jsonify({"status": "ok", "report_id": int(report_id), "reviewed_status": status}), 200


def _closure_status_score(status: str) -> float:
    s = (status or "").strip().lower()
    if s == "approved":
        return 1.0
    if s == "submitted":
        return 0.6
    if s == "rejected":
        return 0.1
    if s == "draft":
        return 0.3
    return 0.0


def _section_scorecard(cur, section_id: int, instructor_id: int, course_name: str, semester: str) -> dict:
    plan_rows = cur.execute(
        """
        SELECT COALESCE(lecture_status,'planned')
        FROM faculty_course_plans
        WHERE section_id = ? AND instructor_id = ?
        """,
        (section_id, instructor_id),
    ).fetchall()
    plan_total = len(plan_rows or [])
    plan_done = sum(1 for r in (plan_rows or []) if (r[0] or "") in ("done", "compensated"))
    plan_progress = (float(plan_done) / float(plan_total)) if plan_total else 0.0

    axis_done_row = cur.execute(
        """
        SELECT COUNT(*)
        FROM faculty_section_axis_status
        WHERE section_id = ? AND instructor_id = ? AND status = 'done'
        """,
        (section_id, instructor_id),
    ).fetchone()
    axis_done = int((axis_done_row[0] if axis_done_row else 0) or 0)
    axis_progress = float(axis_done) / float(len(FACULTY_AXIS_KEYS)) if FACULTY_AXIS_KEYS else 0.0

    closure_row = cur.execute(
        """
        SELECT COALESCE(status,'draft')
        FROM course_closure_reports
        WHERE section_id = ? AND instructor_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (section_id, instructor_id),
    ).fetchone()
    closure_status = (closure_row[0] if closure_row else "draft") or "draft"
    closure_score = _closure_status_score(closure_status)

    assignments_row = cur.execute(
        """
        SELECT COUNT(*)
        FROM faculty_assignments
        WHERE instructor_id = ?
          AND COALESCE(is_active,1) = 1
          AND (section_id = ? OR section_id IS NULL)
        """,
        (instructor_id, section_id),
    ).fetchone()
    assignments_count = int((assignments_row[0] if assignments_row else 0) or 0)

    approved_logs_row = cur.execute(
        """
        SELECT COUNT(*)
        FROM faculty_assignment_logs
        WHERE instructor_id = ?
          AND approval_status = 'approved'
          AND (section_id = ? OR section_id IS NULL)
        """,
        (instructor_id, section_id),
    ).fetchone()
    approved_logs = int((approved_logs_row[0] if approved_logs_row else 0) or 0)
    service_score = 1.0 if (approved_logs > 0 or assignments_count > 0) else 0.0

    # وزن المؤشر: تنفيذ الخطة 40% + المحاور 25% + تقرير الإقفال 20% + التكليفات الرسمية 15%
    overall_score = round((0.40 * plan_progress + 0.25 * axis_progress + 0.20 * closure_score + 0.15 * service_score) * 100.0, 1)
    return {
        "section_id": int(section_id),
        "instructor_id": int(instructor_id),
        "course_name": course_name or "",
        "semester": semester or "",
        "plan_total": int(plan_total),
        "plan_done": int(plan_done),
        "plan_progress": round(plan_progress * 100.0, 1),
        "axis_done": int(axis_done),
        "axis_total": int(len(FACULTY_AXIS_KEYS)),
        "axis_progress": round(axis_progress * 100.0, 1),
        "closure_status": closure_status,
        "assignments_count": int(assignments_count),
        "approved_assignment_logs": int(approved_logs),
        "overall_score": overall_score,
    }


@schedule_bp.route("/faculty_scorecards", methods=["GET"])
@login_required
def faculty_scorecards():
    role = (session.get("user_role") or "").strip()
    if role not in ("admin", "admin_main", "head_of_department", "instructor"):
        return jsonify({"status": "error", "message": "غير مصرح"}), 403

    requested_instructor_id = request.args.get("instructor_id", type=int)
    with get_connection() as conn:
        _sync_schedule_pk_col(conn)
        cur = conn.cursor()
        tuples = []
        if role == "instructor":
            inst_name, instructor_id = _instructor_display_name_for_session()
            if not instructor_id:
                return jsonify({"status": "ok", "items": []}), 200
            if requested_instructor_id and int(requested_instructor_id) != int(instructor_id):
                return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
            tuples = _assigned_section_rows(cur, int(instructor_id), inst_name or "")
        else:
            params = []
            q = f"""
                SELECT s.{SCHEDULE_PK_COL} AS section_id, COALESCE(s.course_name,''), COALESCE(s.day,''), COALESCE(s.time,''),
                       COALESCE(s.room,''), COALESCE(s.instructor,''), COALESCE(s.semester,''), COALESCE(s.instructor_id,0)
                FROM schedule s
                WHERE COALESCE(s.instructor_id,0) > 0
            """
            if requested_instructor_id:
                q += " AND s.instructor_id = ?"
                params.append(int(requested_instructor_id))
            q += f" ORDER BY s.semester, s.course_name, s.{SCHEDULE_PK_COL}"
            rows = cur.execute(q, tuple(params)).fetchall()
            tuples = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in (rows or [])]

        out = []
        for t in tuples or []:
            sid, cn, _day, _tim, _room, _inst, sem = t[0], t[1], t[2], t[3], t[4], t[5], t[6]
            iid = int(t[7]) if len(t) > 7 and t[7] not in (None, "") else int(session.get("instructor_id") or 0)
            if not iid:
                continue
            card = _section_scorecard(cur, int(sid), int(iid), cn or "", sem or "")
            iname_row = cur.execute(
                "SELECT COALESCE(name,'') FROM instructors WHERE id = ? LIMIT 1",
                (int(iid),),
            ).fetchone()
            card["instructor_name"] = (iname_row[0] if iname_row else "") or ""
            out.append(card)
    out.sort(key=lambda x: (x.get("semester") or "", x.get("course_name") or "", int(x.get("section_id") or 0)))
    return jsonify({"status": "ok", "items": out}), 200


@schedule_bp.route("/faculty_cycle_lock", methods=["GET"])
@login_required
def get_faculty_cycle_lock():
    """Return whether the faculty cycle is locked for the current term (readable by any logged-in user)."""
    with get_connection() as conn:
        term_label = _current_term_label_safe(conn)
        locked = _is_faculty_cycle_locked(conn, term_label)
    return jsonify({"status": "ok", "term_label": term_label, "locked": bool(locked)})


@schedule_bp.route("/faculty_cycle_lock", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def set_faculty_cycle_lock():
    data = request.get_json(force=True) or {}
    locked = bool(data.get("locked", False))
    reason = (data.get("reason") or "").strip()
    actor = (session.get("user") or session.get("username") or "").strip() or "system"
    with get_connection() as conn:
        term_label = _current_term_label_safe(conn)
        old_locked = _is_faculty_cycle_locked(conn, term_label)
        if old_locked and (not locked) and not reason:
            return jsonify({"status": "error", "message": "سبب إعادة فتح الدورة مطلوب"}), 400
        _set_faculty_cycle_locked(conn, term_label, locked, actor)
        _append_governance_audit(
            conn=conn,
            actor=actor,
            action=("FACULTY_CYCLE_LOCKED" if locked else "FACULTY_CYCLE_UNLOCKED"),
            scope_type="term",
            scope_id=term_label,
            old_value=("locked" if old_locked else "open"),
            new_value=("locked" if locked else "open"),
            reason=reason,
        )
        conn.commit()
    return jsonify({"status": "ok", "term_label": term_label, "locked": bool(locked)})


@schedule_bp.route("/governance_audit_logs", methods=["GET"])
@role_required("admin", "admin_main", "head_of_department")
def governance_audit_logs():
    action = (request.args.get("action") or "").strip().upper()
    with get_connection() as conn:
        cur = conn.cursor()
        q = """
            SELECT id, ts, actor, action, scope_type, scope_id, old_value, new_value, reason
            FROM governance_audit_logs
            WHERE 1=1
        """
        params = []
        if action:
            q += " AND action = ?"
            params.append(action)
        q += " ORDER BY id DESC LIMIT 300"
        rows = cur.execute(q, tuple(params)).fetchall()
    return jsonify({"status": "ok", "items": [dict(r) for r in (rows or [])]})


def _final_dossier_rows(cur, instructor_id: int | None = None) -> list[dict]:
    _sync_schedule_pk_col(cur.connection)
    q = f"""
        SELECT s.{SCHEDULE_PK_COL} AS section_id,
               COALESCE(s.course_name,'') AS course_name,
               COALESCE(s.semester,'') AS semester,
               COALESCE(s.instructor_id,0) AS instructor_id,
               COALESCE(i.name,'') AS instructor_name
        FROM schedule s
        LEFT JOIN instructors i ON i.id = s.instructor_id
        WHERE COALESCE(s.instructor_id,0) > 0
    """
    params = []
    if instructor_id:
        q += " AND s.instructor_id = ?"
        params.append(int(instructor_id))
    q += f" ORDER BY s.semester, s.course_name, s.{SCHEDULE_PK_COL}"
    rows = cur.execute(q, tuple(params)).fetchall()
    out = []
    for r in rows or []:
        sid = int(r[0])
        iid = int(r[3] or 0)
        card = _section_scorecard(cur, sid, iid, r[1] or "", r[2] or "")
        out.append(
            {
                "section_id": sid,
                "course_name": r[1] or "",
                "semester": r[2] or "",
                "instructor_id": iid,
                "instructor_name": r[4] or "",
                "overall_score": card.get("overall_score", 0),
                "plan_progress": card.get("plan_progress", 0),
                "axis_progress": card.get("axis_progress", 0),
                "closure_status": card.get("closure_status", "draft"),
                "assignments_count": card.get("assignments_count", 0),
                "approved_assignment_logs": card.get("approved_assignment_logs", 0),
            }
        )
    return out


@schedule_bp.route("/faculty_final_dossier", methods=["GET"])
@role_required("admin", "admin_main", "head_of_department")
def faculty_final_dossier():
    instructor_id = request.args.get("instructor_id", type=int)
    with get_connection() as conn:
        cur = conn.cursor()
        rows = _final_dossier_rows(cur, instructor_id=instructor_id)
    return jsonify({"status": "ok", "items": rows})


@schedule_bp.route("/faculty_final_dossier/export", methods=["GET"])
@role_required("admin", "admin_main", "head_of_department")
def export_faculty_final_dossier():
    fmt = (request.args.get("format") or "excel").strip().lower()
    instructor_id = request.args.get("instructor_id", type=int)
    with get_connection() as conn:
        cur = conn.cursor()
        rows = _final_dossier_rows(cur, instructor_id=instructor_id)

    if not rows:
        rows = [{"section_id": "", "course_name": "", "semester": "", "instructor_name": "", "overall_score": 0}]
    df = pd.DataFrame(rows)
    if fmt == "pdf":
        html = "<h3 style='direction:rtl'>ملف الإنجاز النهائي</h3>" + df.to_html(index=False, border=1)
        return pdf_response_from_html(html, filename_prefix="faculty_final_dossier")
    return excel_response_from_df(df, filename_prefix="faculty_final_dossier")


@schedule_bp.route("/student_my_announcements")
@login_required
def student_my_announcements():
    """إعلانات المقررات للطالب الحالي، فقط من شعب مقرراته المسجلة."""
    if session.get("user_role") != "student":
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    sid = (session.get("student_id") or session.get("user") or "").strip()
    if not sid:
        return jsonify({"items": []})
    with get_connection() as conn:
        _sync_schedule_pk_col(conn)
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT a.id,
                   a.section_id,
                   COALESCE(s.course_name,'') AS course_name,
                   COALESCE(a.title,'') AS title,
                   COALESCE(a.body,'') AS body,
                   COALESCE(a.announcement_type,'general') AS announcement_type,
                   COALESCE(a.lecture_date,'') AS lecture_date,
                   COALESCE(a.created_at,'') AS created_at
            FROM faculty_course_announcements a
            JOIN schedule s ON s.{SCHEDULE_PK_COL} = a.section_id
            JOIN registrations r ON r.course_name = s.course_name
            WHERE r.student_id = ?
              AND COALESCE(a.published_to_students, 1) = 1
            ORDER BY a.id DESC
            LIMIT 50
            """,
            (sid,),
        ).fetchall()
    out = [
        {
            "id": int(r[0]),
            "section_id": int(r[1]),
            "course_name": r[2] or "",
            "title": r[3] or "",
            "body": r[4] or "",
            "announcement_type": r[5] or "general",
            "lecture_date": r[6] or "",
            "created_at": r[7] or "",
        }
        for r in (rows or [])
    ]
    return jsonify({"items": out})


@schedule_bp.route("/instructor_timetable")
@login_required
def instructor_timetable():
    """
    جدول الأستاذ الأسبوعي من schedule (قراءة فقط عند نشر الجدول).
    يطابق اسم الأستاذ في الجدول مع اسم السجل في جدول instructors.
    """
    with get_connection() as conn:
        published_at = get_schedule_published_at(conn)
    if published_at is None:
        return jsonify({"rows": [], "published": False})

    if not _is_instructor_effective_session():
        return jsonify({"rows": [], "published": True})

    instructor_id = session.get("instructor_id")
    if not instructor_id:
        return jsonify({"rows": [], "published": True})

    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT COALESCE(TRIM(name), '') FROM instructors WHERE id = ? LIMIT 1",
            (instructor_id,),
        ).fetchone()
    inst_name = (row[0] if row else "") or ""
    if not inst_name.strip():
        return jsonify({"rows": [], "published": True})

    canon = normalize_instructor_name(inst_name)
    try:
        iid_int = int(instructor_id)
    except (TypeError, ValueError):
        return jsonify({"rows": [], "published": True})

    with get_connection() as conn:
        cur = conn.cursor()
        term_name, term_year = get_current_term(conn=conn)
        term_label = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()
        tuples = _assigned_section_rows(cur, iid_int, canon)
        tuples.sort(key=lambda x: ((x[2] or ""), (x[3] or ""), (x[1] or "")))
        out = []
        for t in tuples:
            sid, cn, day, tim, room, inst_txt, sem = t
            if not schedule_semester_matches_current_term(sem, term_label):
                continue
            out.append(
                {
                    "section_id": sid,
                    "course_name": cn,
                    "day": _canonical_schedule_day_label(day),
                    "time": tim,
                    "room": room,
                    "instructor": inst_txt,
                    "semester": sem,
                }
            )
    return jsonify({"rows": out, "published": True})
