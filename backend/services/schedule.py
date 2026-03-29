import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models.models import ScheduleRow
from flask import Blueprint, request, jsonify, render_template, session
from backend.core.auth import login_required, role_required
from collections import defaultdict
import sqlite3, pandas as pd
import logging
import json
import datetime
import base64
from .utilities import (
    get_connection,
    table_to_dicts,
    SEMESTER_LABEL,
    DB_FILE,
    df_from_query,
    excel_response_from_df,
    pdf_response_from_html,
    log_activity,
    get_schedule_published_at,
    set_schedule_published_at,
    get_schedule_updated_at,
    touch_schedule_updated_at,
    get_current_term,
)
from .students import compute_per_student_conflicts, recompute_conflict_report

logger = logging.getLogger(__name__)

schedule_bp = Blueprint("schedule", __name__)

def _time_to_minutes_hhmm(s: str):
    try:
        s = (s or "").strip()
        if len(s) != 5 or s[2] != ":":
            return None
        hh = int(s[0:2]); mm = int(s[3:5])
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
            hh = int(p[0:2]); mm = int(p[3:5])
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

# -----------------------------
# عرض/إضافة صفوف الجدول
# -----------------------------

@schedule_bp.route("/rows")
@login_required
def list_schedule_rows():
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            # استخدام JOIN لتحسين الأداء بدلاً من استعلامات منفصلة في loop
            rows = cur.execute("""
                SELECT 
                    s.rowid AS section_id, 
                    s.course_name, 
                    s.day, 
                    s.time, 
                    s.room, 
                    s.instructor, 
                    s.semester,
                    COUNT(DISTINCT r.student_id) AS student_count
                FROM schedule s
                LEFT JOIN registrations r ON s.course_name = r.course_name
                GROUP BY s.rowid, s.course_name, s.day, s.time, s.room, s.instructor, s.semester
                ORDER BY s.rowid
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
                    'student_count': r[7] or 0
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
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            rows = cur.execute(
                """
                SELECT
                  s.rowid AS section_id,
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
        
        # محاكاة إضافة المقرر مؤقتاً للتحقق من التعارضات
        with get_connection() as conn:
            # حفظ حالة الجدول الحالي
            cur = conn.cursor()
            
            # إضافة مؤقتة للجدول
            cur.execute("""
                INSERT INTO schedule (course_name, day, time, room, instructor, semester)
                VALUES (?,?,?,?,?,?)
            """, (
                course_name,
                day,
                time,
                data.get("room", ""),
                data.get("instructor", ""),
                data.get("semester", SEMESTER_LABEL)
            ))
            temp_rowid = cur.lastrowid
            
            # حساب التعارضات
            conflicts = compute_per_student_conflicts(conn)
            
            # حذف الإضافة المؤقتة
            cur.execute("DELETE FROM schedule WHERE rowid = ?", (temp_rowid,))
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
@schedule_bp.route("/add_row", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def add_schedule_row():
    data = request.get_json(force=True)
    required = ["course_name", "day", "time"]
    for k in required:
        if not data.get(k):
            return jsonify({"status": "error", "message": f"{k} مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO schedule (course_name, day, time, room, instructor, semester)
            VALUES (?,?,?,?,?,?)
        """, (data.get("course_name"), data.get("day"), data.get("time"),
              data.get("room", ""), data.get("instructor", ""), data.get("semester", SEMESTER_LABEL)))
        last = cur.lastrowid
        try:
            touch_schedule_updated_at(conn)
        except Exception:
            pass
        conn.commit()

    try:
        log_activity(
            action="add_schedule_row",
            details=f"section_id={last}, course_name={data.get('course_name')}, day={data.get('day')}, time={data.get('time')}",
        )
    except Exception:
        pass
    # تحديث الجدول النهائي وتقرير التعارضات تلقائياً (خارج with block)
    # Disabled: optimize_with_move_suggestions() is not defined
    # try:
    #     optimize_with_move_suggestions()
    # except Exception as e:
    #     logger.error(f"Error updating optimized schedule after add: {e}")
    return jsonify({"status": "ok", "message": "تم إضافة صف إلى الجدول", "rowid": last}), 200

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
    for k in ("course_name", "day", "time", "room", "instructor", "semester"):
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
            "INSERT OR REPLACE INTO app_settings (key, value_json, updated_at, updated_by) VALUES (?,?,?,?)",
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
        built = _build_schedule_matrix(rows, slots_info.get("slots") or [], include_empty=include_empty)

    cols = built["columns"]
    matrix = built["matrix"]

    # HTML table
    ths = "<th>اليوم / الوقت</th>" + "".join(f"<th>{c}</th>" for c in cols)
    body_rows = ""
    for day in matrix.keys():
        tds = f"<th>{day}</th>"
        for c in cols:
            items = matrix[day].get(c) or []
            if not items:
                tds += "<td></td>"
            else:
                tds += "<td>" + "<br/>".join([str(x) for x in items]) + "</td>"
        body_rows += "<tr>" + tds + "</tr>"

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
        signature_block = f"""
        <div class="sign-wrap">
          <div class="sign-name">محمد فرج الحاسي</div>
          <div class="sign-title">رئيس قسم الهندسة الميكانيكية</div>
        </div>
        """

    meta_bits = f"الفصل: {term_label or '—'} <span class=\"sep\">|</span> التاريخ: {now_print}"
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
        table {{ width: 100%; border-collapse: collapse; table-layout: fixed; margin-top: 0; }}
        th, td {{ border: 1px solid #444; padding: 4px; font-size: 9.8px; vertical-align: top; word-wrap: break-word; }}
        th {{ background: #f3f3f3; font-weight: 700; }}
        td {{ min-height: 18px; line-height: 1.25; }}
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
      <table>
        <thead><tr>{ths}</tr></thead>
        <tbody>{body_rows or ''}</tbody>
      </table>
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
        built = _build_schedule_matrix(rows, slots_info.get("slots") or [], include_empty=include_empty)

    cols = built["columns"]
    matrix = built["matrix"]

    out_rows = []
    for day, by_time in matrix.items():
        row = {"اليوم": day}
        for c in cols:
            items = by_time.get(c) or []
            row[c] = "\n".join(items)
        out_rows.append(row)

    # Append notes row
    notes = []
    if built.get("empty_saved_slots"):
        notes.append("تقسيمات بدون مقررات: " + "، ".join(built["empty_saved_slots"]))
    if built.get("nonmatching_times"):
        notes.append("أوقات غير ضمن التقسيمات (موجودة في البيانات): " + "، ".join(built["nonmatching_times"]))
    if notes:
        note_row = {"اليوم": "ملاحظات"}
        for c in cols:
            note_row[c] = ""
        # ضع النص في أول عمود وقت إن وجد وإلا في اليوم
        if cols:
            note_row[cols[0]] = " | ".join(notes)
        else:
            note_row["اليوم"] = "ملاحظات: " + " | ".join(notes)
        out_rows.append(note_row)

    df = pd.DataFrame(out_rows)
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
            cur = conn.cursor()
            # نسخ الجدول الحالي (schedule) إلى الجدول النهائي (optimized_schedule) لظهوره في صفحة النتائج
            cur.execute("DELETE FROM optimized_schedule")
            cur.execute("""
                INSERT INTO optimized_schedule (section_id, course_name, day, time, room, instructor, semester)
                SELECT rowid, course_name, day, time, COALESCE(room,''), COALESCE(instructor,''), COALESCE(semester,'')
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
        log_activity(action="schedule_publish", details=f"published_at={published_at}")
        return jsonify({"status": "ok", "message": "تم اعتماد ونشر الجدول الدراسي", "published_at": published_at}), 200
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
    elif user_role == "supervisor" or (user_role == "instructor" and int(session.get("is_supervisor") or 0) == 1):
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
        cur = conn.cursor()
        q = """
        SELECT s.rowid AS section_id,
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

    user_role = session.get("user_role")
    if user_role != "instructor":
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

    with get_connection() as conn:
        cur = conn.cursor()
        q = """
        SELECT s.rowid AS section_id,
               s.course_name,
               s.day,
               s.time,
               s.room,
               s.instructor,
               s.semester
        FROM schedule s
        WHERE TRIM(COALESCE(s.instructor, '')) = ?
        ORDER BY s.day, s.time, s.course_name
        """
        rows = cur.execute(q, (inst_name.strip(),)).fetchall()
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
