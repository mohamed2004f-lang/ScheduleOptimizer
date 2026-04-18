import os
import shutil
from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, jsonify, render_template, request, session, current_app, abort
from backend.core.auth import login_required, role_required
from backend.database.database import is_postgresql, table_exists

from .utilities import DB_FILE, get_connection, get_current_term, log_activity

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
        if is_postgresql():
            # إلغاء أي معاملة معطوبة من طلب سابق، ثم autocommit لكل أمر (يتجنب InFailedSqlTransaction).
            raw = getattr(conn, "_conn", None)
            prev_auto = getattr(raw, "autocommit", False) if raw is not None else False
            try:
                if raw is not None:
                    try:
                        raw.rollback()
                    except Exception:
                        pass
                    raw.autocommit = True
                cur = conn.cursor()
                for key, val in (("current_term_name", name), ("current_term_year", year)):
                    cur.execute("DELETE FROM system_settings WHERE key = ?", (key,))
                    cur.execute(
                        "INSERT INTO system_settings (key, value) VALUES (?, ?)",
                        (key, val),
                    )
            finally:
                if raw is not None:
                    try:
                        raw.autocommit = prev_auto
                    except Exception:
                        pass
        else:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO system_settings (key, value) VALUES ('current_term_name', ?)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (name,),
            )
            cur.execute(
                """
                INSERT INTO system_settings (key, value) VALUES ('current_term_year', ?)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
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

        try:
            if table_exists(conn, "students"):
                data["students"] = cur.execute(
                    "SELECT COUNT(*) FROM students"
                ).fetchone()[0]
            if table_exists(conn, "courses"):
                data["courses"] = cur.execute(
                    "SELECT COUNT(*) FROM courses"
                ).fetchone()[0]
            if table_exists(conn, "schedule"):
                data["schedule_rows"] = cur.execute(
                    "SELECT COUNT(*) FROM schedule"
                ).fetchone()[0]
            if table_exists(conn, "registrations"):
                data["registrations"] = cur.execute(
                    "SELECT COUNT(*) FROM registrations"
                ).fetchone()[0]
            if table_exists(conn, "grades"):
                data["grades"] = cur.execute(
                    "SELECT COUNT(*) FROM grades"
                ).fetchone()[0]
            if table_exists(conn, "exams"):
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
            if table_exists(conn, "conflict_report"):
                data["conflict_report_rows"] = cur.execute(
                    "SELECT COUNT(*) FROM conflict_report"
                ).fetchone()[0]
            if table_exists(conn, "exam_conflicts"):
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
# Use project-local backups directory (works for Postgres too).
AUTO_BACKUP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backups", "auto"))
BACKUP_MIN_INTERVAL_SECONDS = 30


def _read_setting(cur, key: str, default: str = "") -> str:
    try:
        row = cur.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
        return (row[0] or default) if row else default
    except Exception:
        return default


def _write_setting(conn, key: str, value: str) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO system_settings (key, value) VALUES (?, ?)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        (key, value),
    )
    conn.commit()


def _db_file_mtime_utc_iso() -> Optional[str]:
    """وقت آخر تعديل لملف قاعدة البيانات (مؤشر آمن لنشاط البيانات دون Git)."""
    try:
        if is_postgresql():
            return None
        path = os.path.abspath(DB_FILE)
        if not os.path.isfile(path):
            return None
        ts = os.path.getmtime(path)
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return None


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_auto_backup_dir() -> None:
    os.makedirs(AUTO_BACKUP_DIR, exist_ok=True)


def _latest_auto_backup_info() -> dict:
    try:
        _ensure_auto_backup_dir()
        files = [
            os.path.join(AUTO_BACKUP_DIR, f)
            for f in os.listdir(AUTO_BACKUP_DIR)
            if f.lower().endswith(".db")
        ]
        if not files:
            return {"exists": False, "name": "", "mtime_utc": None, "age_hours": None}
        latest = max(files, key=lambda p: os.path.getmtime(p))
        ts = os.path.getmtime(latest)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        age_hours = int((datetime.now(timezone.utc) - dt).total_seconds() // 3600)
        return {
            "exists": True,
            "name": os.path.basename(latest),
            "mtime_utc": dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "age_hours": age_hours,
        }
    except Exception:
        return {"exists": False, "name": "", "mtime_utc": None, "age_hours": None}


def _run_db_backup(kind: str = "manual") -> dict:
    _ensure_auto_backup_dir()
    safe_kind = (kind or "manual").strip().lower()
    if safe_kind not in ("manual", "daily", "weekly"):
        safe_kind = "manual"
    if is_postgresql():
        # pg_dump backup (requires pg_dump in PATH)
        from config import DATABASE_URL
        try:
            from sqlalchemy.engine.url import make_url
        except Exception as e:
            raise RuntimeError("SQLAlchemy مطلوب لنسخ PostgreSQL الاحتياطي") from e

        u = make_url(DATABASE_URL or "")
        if u.get_backend_name() != "postgresql":
            raise RuntimeError("DATABASE_URL يجب أن يشير إلى PostgreSQL")
        host = u.host or "localhost"
        port = int(u.port or 5432)
        user = u.username or "postgres"
        db = u.database or ""
        password = u.password or ""

        fname = f"{_now_stamp()}_{safe_kind}_{db}.dump"
        dst = os.path.join(AUTO_BACKUP_DIR, fname)

        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password
        cmd = [
            "pg_dump",
            "-h",
            host,
            "-p",
            str(port),
            "-U",
            user,
            "-d",
            db,
            "-F",
            "c",
            "-f",
            dst,
        ]
        import subprocess

        try:
            subprocess.run(cmd, env=env, check=True)
        except FileNotFoundError as e:
            raise RuntimeError("لم يُعثر على pg_dump. أضف مجلد bin الخاص بـ PostgreSQL إلى PATH.") from e
        return {"path": dst, "name": fname}

    # SQLite legacy backup (kept for archival use only)
    src = os.path.abspath(DB_FILE)
    if not os.path.isfile(src):
        raise FileNotFoundError("ملف قاعدة البيانات غير موجود")
    fname = f"{_now_stamp()}_{safe_kind}_mechanical.db"
    dst = os.path.join(AUTO_BACKUP_DIR, fname)
    shutil.copy2(src, dst)
    return {"path": dst, "name": fname}


def _is_project_status_enabled() -> bool:
    """
    تفعيل صفحة حالة/النسخ الاحتياطي افتراضياً.
    يمكن تعطيلها صراحة عبر: ENABLE_ADMIN_STATUS_PAGE=0
    """
    v = (os.environ.get("ENABLE_ADMIN_STATUS_PAGE", "1") or "").strip().lower()
    return v not in ("0", "false", "no", "off")


def _summarize_database_url_safe(url: str) -> dict:
    """ملخص آمن لـ DATABASE_URL (بدون كلمة مرور)."""
    try:
        from sqlalchemy.engine.url import make_url

        u = make_url(url)
        b = u.get_backend_name()
        if b == "postgresql":
            return {
                "backend": "postgresql",
                "host": u.host,
                "port": u.port,
                "database": u.database,
                "username": u.username,
            }
        if b == "sqlite":
            db = (u.database or "") or ""
            return {"backend": "sqlite", "path_hint": db[:200]}
    except Exception:
        pass
    return {"backend": "unknown", "configured": bool((url or "").strip())}


@admin_bp.route("/system_diagnostics", methods=["GET"])
@role_required("admin", "admin_main")
def system_diagnostics():
    """JSON للمسؤول: بيئة، قاعدة البيانات، النسخ، آخر أخطاء حرجة، عدد المستخدمين."""
    from config import DATABASE_URL, FLASK_ENV
    from backend.core.monitoring import app_stats, get_critical_errors_snapshot

    user_count = None
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            row = cur.execute("SELECT COUNT(*) FROM users").fetchone()
            user_count = int(row[0] if row is not None else 0)
    except Exception:
        pass

    db_meta = _summarize_database_url_safe(DATABASE_URL or "")
    db_meta["active_backend"] = "postgresql" if is_postgresql() else "sqlite"

    uptime = (datetime.now() - app_stats["start_time"]).total_seconds()

    return jsonify(
        {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "flask_env": FLASK_ENV,
            "app_version": (os.environ.get("APP_VERSION") or "2.0.0").strip(),
            "uptime_seconds": uptime,
            "database": db_meta,
            "users_count": user_count,
            "requests_total": app_stats.get("request_count"),
            "errors_http_4xx_5xx_total": app_stats.get("error_count"),
            "last_critical_errors": get_critical_errors_snapshot()[-10:],
        }
    )


@admin_bp.route("/project_status")
@role_required("admin_main")
def admin_project_status_page():
    """صفحة بسيطة: تاريخ آخر تعديل لقاعدة البيانات + ملاحظة إصدار يدوية."""
    if not _is_project_status_enabled():
        abort(404)
    return render_template("admin_project_status.html")


@admin_bp.route("/project_status/data", methods=["GET"])
@role_required("admin_main")
def project_status_data():
    """JSON: آخر تعديل لملف DB + تسمية/ملاحظة محفوظة (لا يُعاد مسار الملف)."""
    if not _is_project_status_enabled():
        abort(404)
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
    backup = _latest_auto_backup_info()
    return jsonify(
        {
            "status": "ok",
            "db_last_modified_utc": mtime_iso,
            "version_label": label.strip(),
            "version_note": note.strip(),
            "latest_backup": backup,
        }
    )


@admin_bp.route("/project_status/note", methods=["POST"])
@role_required("admin_main")
def project_status_save_note():
    """حفظ تسمية إصدار وملاحظة (نص عربي UTF-8 من المتصفح)."""
    if not _is_project_status_enabled():
        abort(404)
    data = request.get_json(force=True) or {}
    label = (data.get("version_label") or "").strip()[:200]
    note = (data.get("version_note") or "").strip()[:4000]
    try:
        with get_connection() as conn:
            _write_setting(conn, PROJECT_VERSION_LABEL_KEY, label)
            _write_setting(conn, PROJECT_VERSION_NOTE_KEY, note)
        log_activity(action="admin_project_status_note_save", details=f"label_len={len(label)}, note_len={len(note)}")
    except Exception:
        current_app.logger.exception("Failed saving project status note")
        return jsonify({"status": "error", "message": "تعذّر حفظ الملاحظة حالياً"}), 500
    return jsonify({"status": "ok", "message": "تم الحفظ"})


@admin_bp.route("/backup_now", methods=["POST"])
@role_required("admin_main")
def backup_now():
    """إنشاء نسخة احتياطية فورية من DB عبر الواجهة."""
    if not _is_project_status_enabled():
        abort(404)
    try:
        now_ts = datetime.now(timezone.utc).timestamp()
        last_ts = float(session.get("last_backup_now_ts") or 0)
        if now_ts - last_ts < BACKUP_MIN_INTERVAL_SECONDS:
            wait_s = int(BACKUP_MIN_INTERVAL_SECONDS - (now_ts - last_ts)) + 1
            return jsonify({
                "status": "error",
                "message": f"تم تنفيذ نسخة احتياطية مؤخرًا. الرجاء الانتظار {wait_s} ثانية.",
            }), 429
        result = _run_db_backup("manual")
        session["last_backup_now_ts"] = now_ts
        log_activity(action="admin_backup_now", details=f"backup={result.get('name','')}")
        return jsonify({"status": "ok", "message": "تم إنشاء نسخة احتياطية بنجاح", "backup": {"name": result.get("name", "")}})
    except Exception:
        current_app.logger.exception("Backup now failed")
        return jsonify({"status": "error", "message": "فشل إنشاء النسخة الاحتياطية. حاول لاحقًا."}), 500
