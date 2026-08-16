import datetime
import logging

from flask import Blueprint, request, jsonify, session
from werkzeug.exceptions import HTTPException

from backend.core.auth import login_required, role_required, _normalize_role
from .utilities import get_connection

academic_calendar_bp = Blueprint("academic_calendar", __name__)
logger = logging.getLogger("backend.services.academic_calendar")


FALL_TITLES = [
    "تجديد القيد وتسجيل المقررات الدراسية (لمدة أسبوع)",
    "تسجيل الطلبة المستجدين (لمدة أسبوع)",
    "بداية الدراسة",
    "آخر موعد لإضافة المقررات الدراسية",
    "بداية الامتحانات الجزئية (التصفية)",
    "نهاية الامتحانات الجزئية (التصفية)",
    "آخر موعد لإسقاط المواد",
    "انتهاء الدراسة",
    "بداية الامتحانات النهائية (للمقررات العملية)",
    "بداية الامتحانات النهائية (للمقررات النظرية)",
    "نهاية الامتحانات النهائية",
    "مناقشة مشاريع التخرج (لمدة ثلاثة أيام)",
    "إعلان النتيجة",
    "استلام طلبات المراجعة لكراسات الإجابة (لمدة أسبوع)",
    "مراجعة كراسات الإجابة للطلاب المتقدمين بتظلم على نتائجهم (لمدة يومين)",
    "إعلان النتيجة النهائية",
]

SPRING_TITLES = [
    "تجديد القيد وتسجيل المقررات الدراسية (لمدة أسبوع)",
    "تسجيل الطلبة المستجدين (لمدة أسبوع)",
    "بداية الدراسة",
    "آخر موعد لإضافة المقررات الدراسية",
    "بداية الامتحانات الجزئية (التصفية)",
    "نهاية الامتحانات الجزئية (التصفية)",
    "آخر موعد لإسقاط المواد",
    "انتهاء الدراسة",
    "بداية الامتحانات النهائية (للمقررات العملية)",
    "بداية الامتحانات النهائية (للمقررات النظرية)",
    "نهاية الامتحانات النهائية",
    "مناقشة مشاريع التخرج (لمدة ثلاثة أيام)",
    "إعلان النتيجة",
    "استلام طلبات المراجعة لكراسات الإجابة",
    "مراجعة كراسات الإجابة للطلاب المتقدمين بتظلم على نتائجهم (لمدة يومين)",
    "إعلان النتيجة النهائية",
]


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_day(raw):
    if raw is None:
        return None
    if hasattr(raw, "isoformat"):
        return str(raw.isoformat())[:10]
    s = str(raw).strip()
    return s[:10] if s else None


def _needs_range(title: str) -> bool:
    return "لمدة" in (title or "")


def _canonical_year(raw: str) -> str:
    from backend.services.term_engine import normalize_academic_year

    return normalize_academic_year(raw) or (raw or "").strip()


def _term_titles(term: str):
    term = (term or "").strip()
    if term in ("fall", "خريف", "فصل الخريف"):
        return "fall", FALL_TITLES
    if term in ("spring", "ربيع", "فصل الربيع"):
        return "spring", SPRING_TITLES
    return None, []


def assemble_calendar_items(*, academic_year: str, term: str, existing: dict) -> list:
    """عناوين افتراضية + صفوف محفوظة — نفس حمولة GET /items."""
    term_n, titles = _term_titles(term)
    if not term_n:
        return []
    out = []
    for i, default_title in enumerate(titles, start=1):
        row = existing.get(i) or {}
        is_deleted = int(row.get("is_deleted") or 0)
        if is_deleted:
            continue
        out.append(
            {
                "item_no": i,
                "title": (row.get("title") or default_title),
                "event_date": _as_day(row.get("event_date")),
                "event_date_start": _as_day(row.get("event_date_start")),
                "is_deleted": 0,
                "updated_at": row.get("updated_at"),
                "is_custom": False,
                "needs_range": _needs_range(row.get("title") or default_title),
            }
        )
    for no in sorted(existing.keys()):
        if no <= len(titles):
            continue
        row = existing.get(no) or {}
        if int(row.get("is_deleted") or 0):
            continue
        out.append(
            {
                "item_no": no,
                "title": (row.get("title") or ""),
                "event_date": _as_day(row.get("event_date")),
                "event_date_start": _as_day(row.get("event_date_start")),
                "is_deleted": 0,
                "updated_at": row.get("updated_at"),
                "is_custom": True,
                "needs_range": _needs_range(row.get("title") or ""),
            }
        )
    return out


def _calendar_has_start_column(conn) -> bool:
    from backend.database.database import fetch_table_columns

    try:
        cols = fetch_table_columns(conn, "academic_calendar") or []
    except Exception:
        return False
    return "event_date_start" in cols


def write_calendar_items(conn, *, academic_year: str, term: str, titles: list, items: list, now: str) -> int:
    """upsert صفوف academic_calendar. لا يعتمد على سياسة النوافذ ولا على عمود اختياري."""
    has_start = _calendar_has_start_column(conn)
    cur = conn.cursor()
    row_max = cur.execute(
        "SELECT COALESCE(MAX(item_no), 0) FROM academic_calendar WHERE academic_year = ? AND term = ?",
        (academic_year, term),
    ).fetchone()
    max_no = len(titles)
    current_max = int(row_max[0] or 0) if row_max else 0
    current_max = max(current_max, max_no)
    written = 0

    if has_start:
        sql = """
            INSERT INTO academic_calendar (
                academic_year, term, item_no, title, event_date, event_date_start, is_deleted, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(academic_year, term, item_no) DO UPDATE SET
              title = excluded.title,
              event_date = excluded.event_date,
              event_date_start = excluded.event_date_start,
              is_deleted = excluded.is_deleted,
              updated_at = excluded.updated_at
            """
    else:
        sql = """
            INSERT INTO academic_calendar (
                academic_year, term, item_no, title, event_date, is_deleted, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(academic_year, term, item_no) DO UPDATE SET
              title = excluded.title,
              event_date = excluded.event_date,
              is_deleted = excluded.is_deleted,
              updated_at = excluded.updated_at
            """

    for it in items:
        raw_no = it.get("item_no")
        try:
            no = int(raw_no) if raw_no is not None and raw_no != "" else 0
        except Exception:
            no = 0

        event_date = (it.get("event_date") or "").strip() or None
        event_date_start = (it.get("event_date_start") or "").strip() or None
        is_deleted = 1 if int(it.get("is_deleted") or 0) else 0
        incoming_title = (it.get("title") or "").strip()

        if no <= 0:
            if not incoming_title:
                continue
            current_max += 1
            no = current_max
            title = incoming_title
        elif 1 <= no <= max_no:
            title = incoming_title or titles[no - 1]
        else:
            title = incoming_title

        if not title:
            continue

        if has_start:
            cur.execute(
                sql,
                (academic_year, term, no, title, event_date, event_date_start, is_deleted, now),
            )
        else:
            cur.execute(
                sql,
                (academic_year, term, no, title, event_date, is_deleted, now),
            )
        written += 1
    return written


@academic_calendar_bp.route("/items", methods=["GET"])
@login_required
def get_items():
    """
    Returns fixed titles + saved dates for a given academic_year and term.
    Query:
      - academic_year: e.g. "2025/2026"
      - term: "fall" | "spring"
    """
    academic_year = _canonical_year((request.args.get("academic_year") or "").strip())
    term_raw = (request.args.get("term") or "").strip()
    term, _titles = _term_titles(term_raw)
    if not academic_year or not term:
        return jsonify({"status": "error", "message": "academic_year و term مطلوبة"}), 400

    with get_connection() as conn:
        from backend.services.term_engine import (
            ensure_term_engine_tables,
            load_calendar_item_rows,
            migrate_spring_new_students_item,
        )

        ensure_term_engine_tables(conn)
        migrate_spring_new_students_item(conn)
        existing = load_calendar_item_rows(conn, academic_year, term)

    out = assemble_calendar_items(academic_year=academic_year, term=term, existing=existing)
    return jsonify({"status": "ok", "academic_year": academic_year, "term": term, "items": out})


@academic_calendar_bp.route("/items", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean")
def upsert_items():
    """
    حفظ تواريخ الإعلان في academic_calendar دائماً.
    preview_only: محاكاة سياسة النوافذ دون كتابة (لوحة التشغيل).
    سياسة التشغيل تُطبَّق بعد الحفظ ولا تمنع تخزين التواريخ.
    """
    try:
        return _upsert_items_impl()
    except HTTPException:
        raise
    except Exception:
        logger.exception("academic_calendar upsert failed")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "تعذر حفظ التقويم الأكاديمي. حدّث الصفحة وأعد المحاولة.",
                    "error": "CALENDAR_SAVE_FAILED",
                }
            ),
            500,
        )


def _upsert_items_impl():
    data = request.get_json(force=True) or {}
    role_n = _normalize_role((session.get("user_role") or "").strip())
    if role_n not in ("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean"):
        return jsonify({"status": "error", "message": "FORBIDDEN", "code": "FORBIDDEN"}), 403
    academic_year = _canonical_year((data.get("academic_year") or "").strip())
    term_raw = (data.get("term") or "").strip()
    term, titles = _term_titles(term_raw)
    items = data.get("items") or []
    preview_only = bool(data.get("preview_only"))
    if not academic_year or not term:
        return jsonify({"status": "error", "message": "academic_year و term مطلوبة"}), 400
    if not isinstance(items, list):
        return jsonify({"status": "error", "message": "items يجب أن تكون قائمة"}), 400

    now = _now_iso()
    actor = (session.get("user") or session.get("username") or "").strip()
    extra = None
    preview = {}
    written = 0
    saved_items = []

    with get_connection() as conn:
        from backend.services.term_engine import (
            ensure_term_engine_tables,
            load_calendar_item_rows,
            migrate_spring_new_students_item,
            on_calendar_saved,
        )
        from backend.services.term_policy import preview_calendar_amendment

        ensure_term_engine_tables(conn)
        migrate_spring_new_students_item(conn)
        existing = load_calendar_item_rows(conn, academic_year, term)
        proposed = assemble_calendar_items(
            academic_year=academic_year, term=term, existing=existing
        )
        by_no = {int(it["item_no"]): it for it in proposed if it.get("item_no")}
        for it in items:
            try:
                no = int(it.get("item_no") or 0)
            except Exception:
                no = 0
            if no <= 0:
                continue
            row = by_no.get(no) or {
                "item_no": no,
                "title": it.get("title") or "",
                "event_date": None,
                "is_deleted": 0,
                "is_custom": True,
            }
            if it.get("title"):
                row["title"] = it.get("title")
            if "event_date" in it:
                row["event_date"] = (it.get("event_date") or "").strip() or None
            if "event_date_start" in it:
                row["event_date_start"] = (it.get("event_date_start") or "").strip() or None
            if int(it.get("is_deleted") or 0):
                row["is_deleted"] = 1
            by_no[no] = row
        proposed_items = [v for v in by_no.values() if not int(v.get("is_deleted") or 0)]
        try:
            preview = preview_calendar_amendment(
                conn, academic_year=academic_year, season=term, items=proposed_items
            ) or {}
        except Exception:
            logger.exception("calendar amendment preview skipped")
            preview = {}
        if preview_only:
            return jsonify(preview)

        written = write_calendar_items(
            conn,
            academic_year=academic_year,
            term=term,
            titles=titles,
            items=items,
            now=now,
        )
        try:
            extra = on_calendar_saved(
                conn,
                academic_year=academic_year,
                season=term,
                actor=actor,
            )
        except Exception:
            logger.exception("term_engine on_calendar_saved after calendar write skipped")
            extra = None
        saved = load_calendar_item_rows(conn, academic_year, term)
        saved_items = assemble_calendar_items(
            academic_year=academic_year, term=term, existing=saved
        )
        conn.commit()

    dated = sum(1 for it in saved_items if it.get("event_date") or it.get("event_date_start"))
    logger.info(
        "academic_calendar saved year=%s term=%s written=%s dated=%s",
        academic_year,
        term,
        written,
        dated,
    )
    payload = {
        "status": "ok",
        "message": f"تم حفظ التقويم الأكاديمي ({dated} تاريخ) لعام {academic_year}",
        "updated_at": now,
        "academic_year": academic_year,
        "term": term,
        "written": written,
        "items": saved_items,
    }
    if extra:
        payload["term_key"] = extra.get("term_key")
        payload["calendar_version"] = extra.get("calendar_version")
    if preview.get("changes"):
        payload["amendment"] = {
            "has_calendar_only": preview.get("has_calendar_only"),
            "has_reject": preview.get("has_reject"),
            "needs_confirm": preview.get("needs_confirm"),
            "changes": preview.get("changes"),
        }
        if preview.get("has_calendar_only"):
            payload["message"] = (
                "تم حفظ التقويم. التشغيل لم يُفتح لأن المرحلة مقفلة — أعد فتح المرحلة بقرار وسبب."
            )
    return jsonify(payload)

