from flask import Blueprint, jsonify
from backend.core.auth import login_required
from .utilities import get_connection

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/summary")
@login_required
def admin_summary():
    """
    إحصائيات سريعة للوحة التحكم:
    - عدد الطلاب
    - عدد المقررات
    - عدد صفوف الجدول (schedule)
    - عدد التسجيلات
    - عدد الدرجات
    - عدد الامتحانات (midterm/final)
    - عدد التعارضات في الجدول والامتحانات (إن وجدت الجداول)
    """
    data = {
        "students": 0,
        "courses": 0,
        "schedule_rows": 0,
        "registrations": 0,
        "grades": 0,
        "exams_total": 0,
        "exams_midterm": 0,
        "exams_final": 0,
        "conflict_report_rows": 0,
        "exam_conflicts_rows": 0,
    }

    with get_connection() as conn:
        cur = conn.cursor()

        def _table_exists(name: str) -> bool:
            try:
                row = cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                    (name,),
                ).fetchone()
                return row is not None
            except Exception:
                return False

        try:
            if _table_exists("students"):
                data["students"] = cur.execute(
                    "SELECT COUNT(*) FROM students"
                ).fetchone()[0]
            if _table_exists("courses"):
                data["courses"] = cur.execute(
                    "SELECT COUNT(*) FROM courses"
                ).fetchone()[0]
            if _table_exists("schedule"):
                data["schedule_rows"] = cur.execute(
                    "SELECT COUNT(*) FROM schedule"
                ).fetchone()[0]
            if _table_exists("registrations"):
                data["registrations"] = cur.execute(
                    "SELECT COUNT(*) FROM registrations"
                ).fetchone()[0]
            if _table_exists("grades"):
                data["grades"] = cur.execute(
                    "SELECT COUNT(*) FROM grades"
                ).fetchone()[0]
            if _table_exists("exams"):
                row = cur.execute(
                    "SELECT COUNT(*) FROM exams"
                ).fetchone()
                data["exams_total"] = row[0] if row else 0
                row_m = cur.execute(
                    "SELECT COUNT(*) FROM exams WHERE exam_type = 'midterm'"
                ).fetchone()
                data["exams_midterm"] = row_m[0] if row_m else 0
                row_f = cur.execute(
                    "SELECT COUNT(*) FROM exams WHERE exam_type = 'final'"
                ).fetchone()
                data["exams_final"] = row_f[0] if row_f else 0
            if _table_exists("conflict_report"):
                data["conflict_report_rows"] = cur.execute(
                    "SELECT COUNT(*) FROM conflict_report"
                ).fetchone()[0]
            if _table_exists("exam_conflicts"):
                data["exam_conflicts_rows"] = cur.execute(
                    "SELECT COUNT(*) FROM exam_conflicts"
                ).fetchone()[0]
        except Exception:
            # في حال فشل أي استعلام، نرجع ما تم حسابه بدون كسر الواجهة
            pass

        # آخر التعديلات من activity_log (إن وجد)
        recent = []
        try:
            cur.execute(
                """
                SELECT ts, actor, action, details
                FROM activity_log
                ORDER BY ts DESC
                LIMIT 10
                """
            )
            rows = cur.fetchall()
            for r in rows:
                recent.append(
                    {
                        "ts": r[0],
                        "actor": r[1],
                        "action": r[2],
                        "details": r[3],
                    }
                )
        except Exception:
            recent = []

    return jsonify({"status": "ok", "data": data, "recent": recent})
