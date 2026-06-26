"""إعدادات وتسجيل الحضور والغياب — مقام ثابت لأسابيع الفصل (افتراضي 16)."""

from __future__ import annotations

import datetime
from typing import Any

from flask import jsonify, request, session

from backend.database.database import is_postgresql, table_exists
from backend.services.attendance_export_core import (
    _attendance_course_key,
    collect_attendance_export_state,
)
from backend.services.utilities import get_connection, get_current_term, log_activity

ATTENDANCE_TERM_WEEKS_KEY = "attendance_term_weeks"
DEFAULT_TERM_WEEKS = 16
MAX_TERM_WEEKS = 30
VALID_STATUSES = frozenset({"present", "absent", "late", "excused"})


def _clamp_term_weeks(raw: int | str | None) -> int:
    try:
        n = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = DEFAULT_TERM_WEEKS
    return max(1, min(MAX_TERM_WEEKS, n))


def get_attendance_term_weeks(conn=None) -> int:
    """عدد أسابيع الفصل للمقام الثابت في نسبة الغياب."""
    if conn is None:
        with get_connection() as c:
            return get_attendance_term_weeks(c)
    cur = conn.cursor()
    if not table_exists(conn, "system_settings"):
        return DEFAULT_TERM_WEEKS
    try:
        row = cur.execute(
            "SELECT value FROM system_settings WHERE key = ? LIMIT 1",
            (ATTENDANCE_TERM_WEEKS_KEY,),
        ).fetchone()
        if row and row[0] not in (None, ""):
            return _clamp_term_weeks(row[0])
    except Exception:
        pass
    return DEFAULT_TERM_WEEKS


def set_attendance_term_weeks(conn, weeks: int) -> int:
    n = _clamp_term_weeks(weeks)
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO system_settings (key, value) VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (ATTENDANCE_TERM_WEEKS_KEY, str(n)),
        )
    else:
        cur.execute(
            """
            INSERT INTO system_settings (key, value) VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value
            """,
            (ATTENDANCE_TERM_WEEKS_KEY, str(n)),
        )
    return n


def _status_label_ar(code: str) -> str:
    c = (code or "").strip().lower()
    return {
        "present": "حضور",
        "absent": "غياب",
        "late": "تأخر",
        "excused": "معذور",
    }.get(c, "")


def compute_absence_stats(
    attendance_by_week: dict[int, str],
    *,
    term_weeks: int,
) -> dict[str, Any]:
    """
    نسبة الغياب = (أسابيع absent ÷ term_weeks) × 100
    الأسابيع غير المُسجَّلة لا تُحسب غياباً.
    """
    absent_weeks = sum(
        1 for wk, st in attendance_by_week.items() if (st or "").strip().lower() == "absent"
    )
    recorded_weeks = sum(1 for st in attendance_by_week.values() if (st or "").strip())
    tw = _clamp_term_weeks(term_weeks)
    pct = round((absent_weeks / tw) * 100.0, 1) if tw > 0 else 0.0
    return {
        "absent_weeks": absent_weeks,
        "recorded_weeks": recorded_weeks,
        "term_weeks": tw,
        "absence_percent": pct,
        "absence_label": f"{absent_weeks}/{tw}",
    }


def _load_course_attendance_map(
    conn,
    cur,
    course_name: str,
    *,
    term_weeks: int,
) -> dict[str, dict[int, str]]:
    out: dict[str, dict[int, str]] = {}
    if not table_exists(conn, "attendance_records"):
        return out
    try:
        rows = cur.execute(
            """
            SELECT student_id, week_number, COALESCE(status, '') AS status
            FROM attendance_records
            WHERE course_name = ? AND week_number BETWEEN 1 AND ?
            """,
            (course_name, term_weeks),
        ).fetchall()
    except Exception:
        return out
    for row in rows:
        sid = str(row[0] if not hasattr(row, "keys") else row["student_id"]).strip()
        try:
            wk = int(row[1] if not hasattr(row, "keys") else row["week_number"])
        except (TypeError, ValueError):
            continue
        st = str(row[2] if not hasattr(row, "keys") else row["status"]).strip().lower()
        if sid and st:
            out.setdefault(sid, {})[wk] = st
    return out


def _verify_course_access(
    get_connection_fn,
    get_current_term_fn,
    normalize_sid_fn,
    course_name: str,
) -> dict[str, Any]:
    """يستخدم منطق التصدير للتحقق من صلاحية المقرر."""
    r = collect_attendance_export_state(
        get_connection_fn,
        get_current_term_fn,
        normalize_sid_fn,
        course_name_lock=course_name,
    )
    if r["kind"] == "http":
        return {"ok": False, "response": r["response"]}
    if r["kind"] == "empty_excel":
        return {
            "ok": False,
            "response": (jsonify({"status": "error", "message": "المقرر غير متاح"}), 404),
        }
    allowed = r.get("selected_courses") or []
    if len(allowed) != 1 or _attendance_course_key(allowed[0]) != _attendance_course_key(course_name):
        return {
            "ok": False,
            "response": (jsonify({"status": "error", "message": "المقرر غير مسموح لحسابك"}), 403),
        }
    return {"ok": True, "state": r}


def build_registration_roster(
    get_connection_fn,
    get_current_term_fn,
    normalize_sid_fn,
    *,
    course_name: str,
    week_number: int | None = None,
) -> dict[str, Any]:
    course_name = (course_name or "").strip()
    if not course_name:
        return {"ok": False, "response": (jsonify({"status": "error", "message": "حدد المقرر"}), 400)}

    chk = _verify_course_access(get_connection_fn, get_current_term_fn, normalize_sid_fn, course_name)
    if not chk.get("ok"):
        return chk

    state = chk["state"]
    cn = state["selected_courses"][0]
    students_list = state["course_students"].get(cn, [])
    term_weeks = get_attendance_term_weeks()

    wk = week_number
    if wk is None:
        try:
            wk = int(str(request.args.get("week", "1")).strip())
        except (TypeError, ValueError):
            wk = 1
    wk = max(1, min(term_weeks, wk))

    with get_connection_fn() as conn:
        cur = conn.cursor()
        att_map = _load_course_attendance_map(conn, cur, cn, term_weeks=term_weeks)

    students_out: list[dict[str, Any]] = []
    for st in students_list:
        sid = normalize_sid_fn(st.get("student_id"))
        if not sid:
            continue
        by_week = att_map.get(sid, {})
        stats = compute_absence_stats(by_week, term_weeks=term_weeks)
        week_st = by_week.get(wk, "")
        students_out.append(
            {
                "student_id": sid,
                "student_name": st.get("student_name") or "",
                "week_status": week_st,
                "week_status_label": _status_label_ar(week_st),
                **stats,
            }
        )

    return {
        "ok": True,
        "data": {
            "course_name": cn,
            "week_number": wk,
            "term_weeks": term_weeks,
            "semester_label": state.get("semester_label") or "",
            "students": students_out,
            "status_options": [
                {"value": "present", "label": "حضور"},
                {"value": "absent", "label": "غياب"},
                {"value": "late", "label": "تأخر"},
                {"value": "excused", "label": "معذور"},
            ],
        },
    }


def save_registration_marks(
    get_connection_fn,
    get_current_term_fn,
    normalize_sid_fn,
    *,
    course_name: str,
    week_number: int,
    marks: list[dict[str, Any]],
) -> dict[str, Any]:
    course_name = (course_name or "").strip()
    if not course_name:
        return {"ok": False, "response": (jsonify({"status": "error", "message": "حدد المقرر"}), 400)}

    try:
        wk = int(week_number)
    except (TypeError, ValueError):
        return {"ok": False, "response": (jsonify({"status": "error", "message": "رقم أسبوع غير صالح"}), 400)}

    term_weeks = get_attendance_term_weeks()
    if wk < 1 or wk > term_weeks:
        return {
            "ok": False,
            "response": (
                jsonify({"status": "error", "message": f"الأسبوع يجب أن يكون بين 1 و {term_weeks}"}),
                400,
            ),
        }

    chk = _verify_course_access(get_connection_fn, get_current_term_fn, normalize_sid_fn, course_name)
    if not chk.get("ok"):
        return chk

    state = chk["state"]
    cn = state["selected_courses"][0]
    allowed_ids = {
        normalize_sid_fn(s.get("student_id"))
        for s in state["course_students"].get(cn, [])
        if s.get("student_id")
    }

    now = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    actor = (session.get("user") or session.get("username") or "").strip() or "system"
    saved = 0

    with get_connection_fn() as conn:
        if not table_exists(conn, "attendance_records"):
            return {
                "ok": False,
                "response": (jsonify({"status": "error", "message": "جدول الحضور غير متوفر"}), 500),
            }
        cur = conn.cursor()
        for item in marks or []:
            sid = normalize_sid_fn(item.get("student_id"))
            if not sid or sid not in allowed_ids:
                continue
            status = (item.get("status") or "").strip().lower()
            if status and status not in VALID_STATUSES:
                continue
            note = (item.get("note") or "").strip()
            if not status:
                try:
                    cur.execute(
                        """
                        DELETE FROM attendance_records
                        WHERE student_id = ? AND course_name = ? AND week_number = ?
                        """,
                        (sid, cn, wk),
                    )
                    saved += 1
                except Exception:
                    pass
                continue
            if is_postgresql():
                cur.execute(
                    """
                    INSERT INTO attendance_records
                        (student_id, course_name, week_number, status, note, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (student_id, course_name, week_number)
                    DO UPDATE SET
                        status = EXCLUDED.status,
                        note = EXCLUDED.note,
                        recorded_at = EXCLUDED.recorded_at
                    """,
                    (sid, cn, wk, status, note, now),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO attendance_records
                        (student_id, course_name, week_number, status, note, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(student_id, course_name, week_number)
                    DO UPDATE SET
                        status = excluded.status,
                        note = excluded.note,
                        recorded_at = excluded.recorded_at
                    """,
                    (sid, cn, wk, status, note, now),
                )
            saved += 1
        try:
            conn.commit()
        except Exception:
            pass

    try:
        log_activity(
            action="attendance_register_save",
            details=f"course={cn}, week={wk}, rows={saved}, by={actor}",
        )
    except Exception:
        pass

    roster = build_registration_roster(
        get_connection_fn,
        get_current_term_fn,
        normalize_sid_fn,
        course_name=cn,
        week_number=wk,
    )
    if not roster.get("ok"):
        return roster
    return {"ok": True, "data": roster["data"], "saved": saved}


def absence_summary_for_export(
    attendance_map: dict,
    *,
    course_name: str,
    student_id: str,
    term_weeks: int,
) -> dict[str, Any]:
    key = (course_name, student_id)
    by_week = attendance_map.get(key, {})
    return compute_absence_stats(by_week, term_weeks=term_weeks)
