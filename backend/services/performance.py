from flask import Blueprint, jsonify, request

from backend.core.auth import role_required
from .utilities import get_connection, excel_response_from_df
from backend.services.grades import _load_transcript_data


performance_bp = Blueprint("performance", __name__)


def _compute_status(ordered_semesters, semester_gpas, cumulative_gpa):
    """
    حساب حالة الطالب (جيد، إنذار أول، إنذار ثانٍ، أكثر) بشكل تقريبي بناءً على المادة 43.
    - نتجاهل أول فصل قُيّد فيه الطالب (لا يصدر فيه إنذار).
    - نعتبر الفصل "منخفضاً" إذا كان معدله الفصلي < 50.
    - نحسب عدد الفصول المنخفضة المتتالية في النهاية:
        0 -> good
        1 -> warning_1
        2 -> warning_2
        3+ -> warning_3
    - إذا كان المعدل التراكمي < 35 بعد مرور فصلين أو أكثر، نضيف ملاحظة عن احتمال الفصل.
    """
    if not ordered_semesters:
        return {"code": "no_data", "label": "لا توجد بيانات درجات"}

    lows = []
    for idx, sem in enumerate(ordered_semesters):
        g = semester_gpas.get(sem, 0.0)
        if idx == 0:
            lows.append(False)
        else:
            lows.append(g < 50.0)

    consecutive_lows = 0
    for idx in range(len(lows) - 1, -1, -1):
        if not lows[idx]:
            break
        if idx == 0:
            break
        consecutive_lows += 1

    if consecutive_lows == 0:
        status_code = "good"
        label = "طالب في وضع أكاديمي سليم"
    elif consecutive_lows == 1:
        status_code = "warning_1"
        label = "إنذار أكاديمي أول (معدل فصلي أقل من 50%)"
    elif consecutive_lows == 2:
        status_code = "warning_2"
        label = "إنذار أكاديمي ثانٍ (فصلان متتاليان دون إزالة الإنذار)"
    else:
        status_code = "warning_3"
        label = "أكثر من إنذارين متتاليين (يستدعي دراسة حالة للفصل المحتمل)"

    extra_notes = []
    try:
        cgpa = float(cumulative_gpa or 0.0)
    except Exception:
        cgpa = 0.0

    if len(ordered_semesters) >= 2 and cgpa < 35.0:
        extra_notes.append("المعدل التراكمي أقل من 35% بعد فصلين على الأقل (وفق المادة 44 قد يعرّض الطالب للفصل).")

    if extra_notes:
        label = f"{label} — " + " ".join(extra_notes)

    return {"code": status_code, "label": label}


@performance_bp.route("/report")
@role_required("admin", "supervisor")
def performance_report():
    """
    تقرير موجز لأداء الطلبة:
    - آخر فصلين (أو ثلاثة فصول) مع معدلاتهم.
    - المعدل التراكمي والوحدات المنجزة.
    - حالة تقريبية حسب لائحة الإنذار (مادة 43) وبعض إشارات الفصل (مادة 44).
    """
    results = []

    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT student_id, COALESCE(student_name,'') AS student_name, COALESCE(join_year,'') AS join_year "
            "FROM students ORDER BY student_id"
        ).fetchall()

        for r in rows:
            sid = r[0]
            name = r[1]
            join_year = r[2]

            data = _load_transcript_data(sid)
            ordered = data.get("ordered_semesters", []) or []
            sem_gpas = data.get("semester_gpas", {}) or {}
            cumulative_gpa = data.get("cumulative_gpa", 0.0)
            completed_units = int(data.get("completed_units") or 0)

            last_semester = ordered[-1] if len(ordered) >= 1 else ""
            prev_semester = ordered[-2] if len(ordered) >= 2 else ""
            third_semester = ordered[-3] if len(ordered) >= 3 else ""

            last_gpa = sem_gpas.get(last_semester, None) if last_semester else None
            prev_gpa = sem_gpas.get(prev_semester, None) if prev_semester else None
            third_gpa = sem_gpas.get(third_semester, None) if third_semester else None

            status = _compute_status(ordered, sem_gpas, cumulative_gpa)

            exc_row = cur.execute(
                """
                SELECT id, type, note, is_active
                FROM student_exceptions
                WHERE student_id = ? AND type = 'extra_chance'
                ORDER BY id DESC
                LIMIT 1
                """,
                (sid,),
            ).fetchone()
            has_extra = bool(exc_row and exc_row[3])
            extra_note = exc_row[2] if exc_row else ""

            results.append(
                {
                    "student_id": sid,
                    "student_name": name,
                    "join_year": join_year,
                    "last_semester": last_semester,
                    "last_semester_gpa": last_gpa,
                    "prev_semester": prev_semester,
                    "prev_semester_gpa": prev_gpa,
                    "third_semester": third_semester,
                    "third_semester_gpa": third_gpa,
                    "cumulative_gpa": cumulative_gpa,
                    "completed_units": completed_units,
                    "status_code": status["code"],
                    "status_label": status["label"],
                    "extra_chance": has_extra,
                    "extra_chance_note": extra_note or "",
                }
            )

    return jsonify({"students": results})


@performance_bp.route("/status/<student_id>")
@role_required("admin", "supervisor", "student")
def performance_status(student_id: str):
    """
    إرجاع حالة أكاديمية موجزة لطالب واحد:
    - status_code, status_label
    - cumulative_gpa, completed_units
    - extra_chance (فرصة استثنائية) إن وُجدت.
    يستخدمها كشف الدرجات لعرض ملاحظة سريعة.
    """
    sid = (student_id or "").strip()
    if not sid:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        data = _load_transcript_data(sid)
        ordered = data.get("ordered_semesters", []) or []
        sem_gpas = data.get("semester_gpas", {}) or {}
        cumulative_gpa = data.get("cumulative_gpa", 0.0)
        completed_units = int(data.get("completed_units") or 0)

        status = _compute_status(ordered, sem_gpas, cumulative_gpa)

        exc_row = cur.execute(
            """
            SELECT id, type, note, is_active
            FROM student_exceptions
            WHERE student_id = ? AND type = 'extra_chance'
            ORDER BY id DESC
            LIMIT 1
            """,
            (sid,),
        ).fetchone()
        has_extra = bool(exc_row and exc_row[3])
        extra_note = exc_row[2] if exc_row else ""

    return jsonify(
        {
            "student_id": sid,
            "status_code": status["code"],
            "status_label": status["label"],
            "cumulative_gpa": cumulative_gpa,
            "completed_units": completed_units,
            "extra_chance": has_extra,
            "extra_chance_note": extra_note or "",
        }
    )


@performance_bp.route("/extra_chance", methods=["POST"])
@role_required("admin")
def set_extra_chance():
    """
    منح / إلغاء فرصة استثنائية لطالب.
    body:
      - student_id (مطلوب)
      - active: true/false (مطلوب)
      - note: ملاحظة اختيارية
      - created_by: اسم المستخدم (اختياري؛ يمكن إرساله من الواجهة)
    """
    data = request.get_json(force=True) or {}
    sid = (data.get("student_id") or "").strip()
    active_raw = data.get("active")
    note = (data.get("note") or "").strip() or None
    created_by = (data.get("created_by") or "").strip() or None

    if not sid:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400

    is_active = 1 if bool(active_raw) else 0

    from datetime import datetime

    now = datetime.utcnow().isoformat()

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO student_exceptions (student_id, type, note, created_by, created_at, is_active)
            VALUES (?, 'extra_chance', ?, ?, ?, ?)
            """,
            (sid, note, created_by, now, is_active),
        )
        conn.commit()

    return jsonify({"status": "ok"})


@performance_bp.route("/export")
@role_required("admin")
def export_performance_excel():
    """
    تصدير تقرير الأداء (نفس بيانات /report) إلى ملف Excel.
    """
    from pandas import DataFrame

    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT student_id, COALESCE(student_name,'') AS student_name, COALESCE(join_year,'') AS join_year "
            "FROM students ORDER BY student_id"
        ).fetchall()

        data_rows = []
        for r in rows:
            sid = r[0]
            name = r[1]
            join_year = r[2]

            tr = _load_transcript_data(sid)
            ordered = tr.get("ordered_semesters", []) or []
            sem_gpas = tr.get("semester_gpas", {}) or {}
            cumulative_gpa = tr.get("cumulative_gpa", 0.0)
            completed_units = int(tr.get("completed_units") or 0)

            last_semester = ordered[-1] if len(ordered) >= 1 else ""
            prev_semester = ordered[-2] if len(ordered) >= 2 else ""
            third_semester = ordered[-3] if len(ordered) >= 3 else ""

            last_gpa = sem_gpas.get(last_semester, None) if last_semester else None
            prev_gpa = sem_gpas.get(prev_semester, None) if prev_semester else None
            third_gpa = sem_gpas.get(third_semester, None) if third_semester else None

            status = _compute_status(ordered, sem_gpas, cumulative_gpa)

            exc_row = cur.execute(
                """
                SELECT id, type, note, is_active
                FROM student_exceptions
                WHERE student_id = ? AND type = 'extra_chance'
                ORDER BY id DESC
                LIMIT 1
                """,
                (sid,),
            ).fetchone()
            has_extra = bool(exc_row and exc_row[3])
            extra_note = exc_row[2] if exc_row else ""

            data_rows.append(
                {
                    "student_id": sid,
                    "student_name": name,
                    "join_year": join_year,
                    "last_semester": last_semester,
                    "last_semester_gpa": last_gpa,
                    "prev_semester": prev_semester,
                    "prev_semester_gpa": prev_gpa,
                    "third_semester": third_semester,
                    "third_semester_gpa": third_gpa,
                    "cumulative_gpa": cumulative_gpa,
                    "completed_units": completed_units,
                    "status_code": status["code"],
                    "status_label": status["label"],
                    "extra_chance": has_extra,
                    "extra_chance_note": extra_note or "",
                }
            )

    df = DataFrame(data_rows)
    return excel_response_from_df(df, filename_prefix="performance_report")

