import os
import shutil
from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, jsonify, render_template, request, session, current_app, abort
from backend.core.auth import login_required, role_required
from backend.core import department_scope_policy as dept_scope_policy
from backend.database.database import is_postgresql, table_exists, fetch_table_columns

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
    label = f"{name} {year}".strip()
    return jsonify(
        {
            "status": "ok",
            "message": (
                "تم حفظ الفصل الحالي. "
                "الفصول المغلقة سابقاً تبقى مقفلة تحت ملصقها — الفصل الجديد دورة تشغيل مستقلة."
            ),
            "term_name": name,
            "term_year": year,
            "term_label": label,
        }
    )


@admin_bp.route("/settings/attendance_term_weeks", methods=["GET"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "head_of_department")
def get_attendance_term_weeks_setting():
    """عدد أسابيع الفصل لحساب نسبة الغياب (مقام ثابت — افتراضي 16)."""
    from backend.services.attendance_registration import (
        DEFAULT_TERM_WEEKS,
        MAX_TERM_WEEKS,
        get_attendance_term_weeks,
    )

    with get_connection() as conn:
        weeks = get_attendance_term_weeks(conn)
    return jsonify(
        {
            "status": "ok",
            "term_weeks": weeks,
            "default_weeks": DEFAULT_TERM_WEEKS,
            "max_weeks": MAX_TERM_WEEKS,
        }
    )


@admin_bp.route("/settings/attendance_term_weeks", methods=["POST"])
@role_required("admin", "admin_main", "system_admin", "college_dean")
def set_attendance_term_weeks_setting():
    """حفظ عدد أسابيع الفصل لحساب نسبة الغياب."""
    from backend.services.attendance_registration import set_attendance_term_weeks

    data = request.get_json(force=True) or {}
    try:
        weeks = int(data.get("term_weeks"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "term_weeks مطلوب (رقم صحيح)"}), 400
    with get_connection() as conn:
        saved = set_attendance_term_weeks(conn, weeks)
        try:
            conn.commit()
        except Exception:
            pass
    log_activity(
        session.get("user") or session.get("username") or "—",
        "attendance_term_weeks",
        f"term_weeks={saved}",
    )
    return jsonify({"status": "ok", "message": "تم حفظ عدد أسابيع الفصل", "term_weeks": saved})


@admin_bp.route("/settings/course_eval_response_rate", methods=["GET"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "head_of_department")
def get_course_eval_response_rate_setting():
    """قراءة نسبة الاستجابة المطلوبة لإظهار نتائج تقييم المقرر."""
    from backend.services.survey_analytics import (
        COURSE_EVAL_DEFAULT_RATE_PERCENT,
        COURSE_EVAL_RATE_MAX_PERCENT,
        COURSE_EVAL_RATE_MIN_PERCENT,
        get_course_eval_response_rate_percent,
    )

    with get_connection() as conn:
        pct = get_course_eval_response_rate_percent(conn)
    return jsonify(
        {
            "status": "ok",
            "rate_percent": pct,
            "default_percent": COURSE_EVAL_DEFAULT_RATE_PERCENT,
            "min_percent": COURSE_EVAL_RATE_MIN_PERCENT,
            "max_percent": COURSE_EVAL_RATE_MAX_PERCENT,
        }
    )


@admin_bp.route("/settings/course_eval_response_rate", methods=["POST"])
@role_required("admin", "admin_main", "system_admin", "college_dean")
def set_course_eval_response_rate_setting():
    """حفظ نسبة الاستجابة المطلوبة لإظهار نتائج تقييم المقرر."""
    from backend.services.survey_analytics import set_course_eval_response_rate_percent

    data = request.get_json(force=True) or {}
    try:
        pct = int(data.get("rate_percent"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "rate_percent مطلوب (رقم صحيح)"}), 400
    with get_connection() as conn:
        saved = set_course_eval_response_rate_percent(conn, pct)
    log_activity(
        session.get("user") or session.get("username") or "—",
        "course_eval_response_rate",
        f"rate_percent={saved}",
    )
    return jsonify(
        {
            "status": "ok",
            "message": f"تم حفظ نسبة تجميع تقييم المقرر: {saved}%",
            "rate_percent": saved,
        }
    )


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
            username = (session.get("user") or session.get("username") or "").strip()
            scope_mode, scope_dept_id = dept_scope_policy.resolve_users_list_scope(conn, username)
            dept_scoped = scope_mode == "department" and scope_dept_id is not None

            cols_courses = fetch_table_columns(conn, "courses") if table_exists(conn, "courses") else []
            has_owning_course = "owning_department_id" in cols_courses

            st_where, st_params = dept_scope_policy.resolve_scope_sql_for_students_table(conn, username)
            reg_join_where, reg_join_params = dept_scope_policy.resolve_scope_sql_for_aliased_student(
                conn, username, "st"
            )

            if table_exists(conn, "students"):
                if st_where:
                    data["students"] = cur.execute(
                        f"SELECT COUNT(*) FROM students WHERE {st_where}",
                        st_params,
                    ).fetchone()[0]
                else:
                    data["students"] = cur.execute("SELECT COUNT(*) FROM students").fetchone()[0]

            if table_exists(conn, "courses"):
                if dept_scoped and has_owning_course:
                    data["courses"] = cur.execute(
                        "SELECT COUNT(*) FROM courses WHERE owning_department_id = ?",
                        (int(scope_dept_id),),
                    ).fetchone()[0]
                else:
                    data["courses"] = cur.execute("SELECT COUNT(*) FROM courses").fetchone()[0]

            if table_exists(conn, "schedule"):
                if dept_scoped and has_owning_course:
                    data["schedule_rows"] = cur.execute(
                        """
                        SELECT COUNT(*) FROM schedule sch
                        INNER JOIN courses crs ON crs.course_name = sch.course_name
                        WHERE crs.owning_department_id = ?
                        """,
                        (int(scope_dept_id),),
                    ).fetchone()[0]
                else:
                    data["schedule_rows"] = cur.execute("SELECT COUNT(*) FROM schedule").fetchone()[0]

            if table_exists(conn, "registrations"):
                if reg_join_where:
                    data["registrations"] = cur.execute(
                        f"""
                        SELECT COUNT(*) FROM registrations r
                        INNER JOIN students st ON st.student_id = r.student_id
                        WHERE {reg_join_where}
                        """,
                        reg_join_params,
                    ).fetchone()[0]
                else:
                    data["registrations"] = cur.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]

            if table_exists(conn, "grades"):
                if reg_join_where:
                    data["grades"] = cur.execute(
                        f"""
                        SELECT COUNT(*) FROM grades g
                        INNER JOIN students st ON st.student_id = g.student_id
                        WHERE {reg_join_where}
                        """,
                        reg_join_params,
                    ).fetchone()[0]
                else:
                    data["grades"] = cur.execute("SELECT COUNT(*) FROM grades").fetchone()[0]

            if table_exists(conn, "exams"):
                if dept_scoped and has_owning_course:
                    row = cur.execute(
                        """
                        SELECT COUNT(*) FROM exams e
                        INNER JOIN courses crs ON crs.course_name = e.course_name
                        WHERE crs.owning_department_id = ?
                        """,
                        (int(scope_dept_id),),
                    ).fetchone()
                    data["exams_total"] = row[0] if row else 0
                    row_m = cur.execute(
                        """
                        SELECT COUNT(*) FROM exams e
                        INNER JOIN courses crs ON crs.course_name = e.course_name
                        WHERE crs.owning_department_id = ?
                          AND e.exam_type = 'midterm'
                        """,
                        (int(scope_dept_id),),
                    ).fetchone()
                    data["exams_midterm"] = row_m[0] if row_m else 0
                    row_f = cur.execute(
                        """
                        SELECT COUNT(*) FROM exams e
                        INNER JOIN courses crs ON crs.course_name = e.course_name
                        WHERE crs.owning_department_id = ?
                          AND e.exam_type = 'final'
                        """,
                        (int(scope_dept_id),),
                    ).fetchone()
                    data["exams_final"] = row_f[0] if row_f else 0
                else:
                    row = cur.execute("SELECT COUNT(*) FROM exams").fetchone()
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
                if reg_join_where:
                    data["conflict_report_rows"] = cur.execute(
                        f"""
                        SELECT COUNT(*) FROM conflict_report cr
                        INNER JOIN students st ON st.student_id = cr.student_id
                        WHERE {reg_join_where}
                        """,
                        reg_join_params,
                    ).fetchone()[0]
                else:
                    data["conflict_report_rows"] = cur.execute(
                        "SELECT COUNT(*) FROM conflict_report"
                    ).fetchone()[0]

            if table_exists(conn, "exam_conflicts"):
                if reg_join_where:
                    data["exam_conflicts_rows"] = cur.execute(
                        f"""
                        SELECT COUNT(*) FROM exam_conflicts ec
                        INNER JOIN students st ON st.student_id = ec.student_id
                        WHERE {reg_join_where}
                        """,
                        reg_join_params,
                    ).fetchone()[0]
                else:
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
        exts = (".dump", ".sql") if is_postgresql() else (".db",)
        files = [
            os.path.join(AUTO_BACKUP_DIR, f)
            for f in os.listdir(AUTO_BACKUP_DIR)
            if f.lower().endswith(exts)
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
    if not is_postgresql():
        raise RuntimeError("النسخ الاحتياطي متاح لـ PostgreSQL فقط. عيّن DATABASE_URL.")
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
@role_required("admin", "admin_main", "system_admin", "college_dean")
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
@role_required("admin_main", "system_admin", "college_dean")
def admin_project_status_page():
    """صفحة بسيطة: تاريخ آخر تعديل لقاعدة البيانات + ملاحظة إصدار يدوية."""
    if not _is_project_status_enabled():
        abort(404)
    return render_template("admin_project_status.html")


@admin_bp.route("/project_status/data", methods=["GET"])
@role_required("admin_main", "system_admin", "college_dean")
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
@role_required("admin_main", "system_admin", "college_dean")
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
@role_required("admin_main", "system_admin", "college_dean")
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


@admin_bp.route("/backup_page")
@role_required("admin_main", "system_admin")
def admin_backup_page():
    """صفحة النسخ الاحتياطي الكامل للأدمن الرئيسي."""
    return render_template("admin_backup.html")


@admin_bp.route("/backup/status", methods=["GET"])
@role_required("admin_main", "system_admin")
def admin_backup_status():
    from backend.services.backup_jobs import backup_status

    return jsonify({"status": "ok", **backup_status()})


@admin_bp.route("/backup/full", methods=["POST"])
@role_required("admin_main", "system_admin")
def admin_backup_full():
    """نسخة كاملة: قاعدة + مرفقات → القرص المُعرَّف في BACKUP_MIRROR_ROOT."""
    from backend.services.backup_jobs import run_full_backup

    try:
        now_ts = datetime.now(timezone.utc).timestamp()
        last_ts = float(session.get("last_backup_full_ts") or 0)
        if now_ts - last_ts < BACKUP_MIN_INTERVAL_SECONDS:
            wait_s = int(BACKUP_MIN_INTERVAL_SECONDS - (now_ts - last_ts)) + 1
            return jsonify({
                "status": "error",
                "message": f"تم تنفيذ نسخة احتياطية مؤخرًا. انتظر {wait_s} ثانية.",
            }), 429
        result = run_full_backup()
        session["last_backup_full_ts"] = now_ts
        session["last_backup_now_ts"] = now_ts
        log_activity(
            action="admin_backup_full",
            details=f"mirror={result.get('mirror_root','')} dump={result.get('dump_name','')}",
        )
        return jsonify({
            "status": "ok",
            "message": "تم إنشاء نسخة احتياطية كاملة بنجاح",
            "backup": result,
        })
    except Exception as exc:
        current_app.logger.exception("Full backup failed")
        msg = str(exc).strip() or "فشل إنشاء النسخة الاحتياطية الكاملة"
        return jsonify({"status": "error", "message": msg}), 500
