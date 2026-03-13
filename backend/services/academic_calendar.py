import datetime

from flask import Blueprint, request, jsonify, session

from backend.core.auth import login_required, role_required
from .utilities import get_connection

academic_calendar_bp = Blueprint("academic_calendar", __name__)


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


def _term_titles(term: str):
    term = (term or "").strip()
    if term in ("fall", "خريف", "فصل الخريف"):
        return "fall", FALL_TITLES
    if term in ("spring", "ربيع", "فصل الربيع"):
        return "spring", SPRING_TITLES
    return None, []


@academic_calendar_bp.route("/items", methods=["GET"])
@login_required
def get_items():
    """
    Returns fixed titles + saved dates for a given academic_year and term.
    Query:
      - academic_year: e.g. "2025/2026"
      - term: "fall" | "spring"
    """
    academic_year = (request.args.get("academic_year") or "").strip()
    term_raw = (request.args.get("term") or "").strip()
    term, titles = _term_titles(term_raw)
    if not academic_year or not term:
        return jsonify({"status": "error", "message": "academic_year و term مطلوبة"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT item_no, title, event_date, is_deleted, updated_at
            FROM academic_calendar
            WHERE academic_year = ? AND term = ?
            ORDER BY item_no
            """,
            (academic_year, term),
        ).fetchall()
        existing = {
            int(r[0]): {"title": r[1], "event_date": r[2], "is_deleted": int(r[3] or 0), "updated_at": r[4]}
            for r in rows
        }

    out = []
    # 1) العناوين الافتراضية (مع إمكانية override من قاعدة البيانات)
    for i, default_title in enumerate(titles, start=1):
        row = existing.get(i) or {}
        is_deleted = int(row.get("is_deleted") or 0)
        if is_deleted:
            continue
        out.append(
            {
                "item_no": i,
                "title": (row.get("title") or default_title),
                "event_date": row.get("event_date"),
                "is_deleted": 0,
                "updated_at": row.get("updated_at"),
                "is_custom": False,
            }
        )

    # 2) أي عناصر إضافية (مخصصة) تم حفظها في قاعدة البيانات
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
                "event_date": row.get("event_date"),
                "is_deleted": 0,
                "updated_at": row.get("updated_at"),
                "is_custom": True,
            }
        )
    return jsonify({"status": "ok", "academic_year": academic_year, "term": term, "items": out})


@academic_calendar_bp.route("/items", methods=["POST"])
@login_required
@role_required("admin")
def upsert_items():
    """
    Save dates for items. Admin only.
    body:
      - academic_year
      - term: fall/spring
      - items: [{item_no, title?, event_date?, is_deleted?}]
        - item_no: إذا كان 0 أو غير موجود -> يُنشأ عنصر جديد (عنوان مخصص)
    """
    data = request.get_json(force=True) or {}
    academic_year = (data.get("academic_year") or "").strip()
    term_raw = (data.get("term") or "").strip()
    term, titles = _term_titles(term_raw)
    items = data.get("items") or []
    if not academic_year or not term:
        return jsonify({"status": "error", "message": "academic_year و term مطلوبة"}), 400
    if not isinstance(items, list):
        return jsonify({"status": "error", "message": "items يجب أن تكون قائمة"}), 400

    max_no = len(titles)
    now = _now_iso()

    with get_connection() as conn:
        cur = conn.cursor()
        # احصل على أكبر رقم حالياً لإضافة عناصر جديدة
        row_max = cur.execute(
            "SELECT COALESCE(MAX(item_no), 0) FROM academic_calendar WHERE academic_year = ? AND term = ?",
            (academic_year, term),
        ).fetchone()
        current_max = int(row_max[0] or 0) if row_max else 0
        current_max = max(current_max, max_no)

        for it in items:
            raw_no = it.get("item_no")
            try:
                no = int(raw_no) if raw_no is not None and raw_no != "" else 0
            except Exception:
                no = 0

            event_date = (it.get("event_date") or "").strip() or None
            is_deleted = 1 if int(it.get("is_deleted") or 0) else 0

            # title: الافتراضي للعناصر القياسية، ومطلوب للعناصر الجديدة
            incoming_title = (it.get("title") or "").strip()

            if no <= 0:
                # عنصر جديد (مخصص)
                if not incoming_title:
                    continue
                current_max += 1
                no = current_max
                title = incoming_title
            elif 1 <= no <= max_no:
                # عنصر قياسي: يمكن تعديل عنوانه أو إبقاءه الافتراضي
                title = incoming_title or titles[no - 1]
            else:
                # عنصر مخصص موجود
                title = incoming_title

            if not title:
                continue

            cur.execute(
                """
                INSERT INTO academic_calendar (academic_year, term, item_no, title, event_date, is_deleted, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(academic_year, term, item_no) DO UPDATE SET
                  title = excluded.title,
                  event_date = excluded.event_date,
                  is_deleted = excluded.is_deleted,
                  updated_at = excluded.updated_at
                """,
                (academic_year, term, no, title, event_date, is_deleted, now),
            )
        conn.commit()

    return jsonify({"status": "ok", "message": "تم حفظ التقويم الأكاديمي", "updated_at": now})

