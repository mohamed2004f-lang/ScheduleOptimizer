import os
from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, jsonify, render_template, request
from backend.core.auth import login_required, role_required
from .utilities import DB_FILE, get_connection, get_current_term

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/settings/current_term", methods=["GET"])
@login_required
def get_current_term_api():
    """قراءة الفصل الحالي (اسم + سنة) للعرض أو التعيين الافتراضي."""
    name, year = get_current_term()
    return jsonify({"status": "ok", "term_name": name, "term_year": year})


@admin_bp.route("/settings/current_term", methods=["POST"])
@role_required("admin")
def set_current_term():
    """حفظ اسم الفصل الحالي وسنة الفصل في system_settings."""
    data = request.get_json(force=True) or {}
    name = (data.get("term_name") or "").strip()
    year = (data.get("term_year") or "").strip()
    if not name:
        return jsonify({"status": "error", "message": "term_name مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', ?)",
            (name,),
        )
        cur.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', ?)",
            (year,),
        )
        conn.commit()
    return jsonify({"status": "ok", "message": "تم حفظ الفصل الحالي", "term_name": name, "term_year": year})


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


# --- إصدار المشروع / آخر تعديل للبيانات (بدون Git — يتجنب مشاكل الترميز وكشف المستودع) ---

PROJECT_VERSION_LABEL_KEY = "project_version_label"
PROJECT_VERSION_NOTE_KEY = "project_version_note"


def _read_setting(cur, key: str, default: str = "") -> str:
    try:
        row = cur.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
        return (row[0] or default) if row else default
    except Exception:
        return default


def _write_setting(conn, key: str, value: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()


def _db_file_mtime_utc_iso() -> Optional[str]:
    """وقت آخر تعديل لملف قاعدة البيانات (مؤشر آمن لنشاط البيانات دون Git)."""
    try:
        path = os.path.abspath(DB_FILE)
        if not os.path.isfile(path):
            return None
        ts = os.path.getmtime(path)
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return None


@admin_bp.route("/project_status")
@role_required("admin_main")
def admin_project_status_page():
    """صفحة بسيطة: تاريخ آخر تعديل لقاعدة البيانات + ملاحظة إصدار يدوية."""
    return render_template("admin_project_status.html")


@admin_bp.route("/project_status/data", methods=["GET"])
@role_required("admin_main")
def project_status_data():
    """JSON: آخر تعديل لملف DB + تسمية/ملاحظة محفوظة (لا يُعاد مسار الملف)."""
    mtime_iso = _db_file_mtime_utc_iso()
    label = ""
    note = ""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            label = _read_setting(cur, PROJECT_VERSION_LABEL_KEY, "")
            note = _read_setting(cur, PROJECT_VERSION_NOTE_KEY, "")
    except Exception:
        pass
    return jsonify(
        {
            "status": "ok",
            "db_last_modified_utc": mtime_iso,
            "version_label": label.strip(),
            "version_note": note.strip(),
        }
    )


@admin_bp.route("/project_status/note", methods=["POST"])
@role_required("admin_main")
def project_status_save_note():
    """حفظ تسمية إصدار وملاحظة (نص عربي UTF-8 من المتصفح)."""
    data = request.get_json(force=True) or {}
    label = (data.get("version_label") or "").strip()[:200]
    note = (data.get("version_note") or "").strip()[:4000]
    try:
        with get_connection() as conn:
            _write_setting(conn, PROJECT_VERSION_LABEL_KEY, label)
            _write_setting(conn, PROJECT_VERSION_NOTE_KEY, note)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:200]}), 500
    return jsonify({"status": "ok", "message": "تم الحفظ"})
