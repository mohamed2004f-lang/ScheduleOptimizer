from flask import Flask, render_template, redirect, url_for, jsonify, session, request, abort, send_from_directory
from flask_wtf.csrf import CSRFProtect, CSRFError
from backend.database.database import ensure_tables, is_postgresql, close_pool
from config import DATABASE_URL, FLASK_ENV, FLASK_DEBUG
import atexit

# Blueprints
from backend.services.students import students_bp
from backend.services.courses import courses_bp
from backend.services.grades import grades_bp
from backend.services.schedule import schedule_bp
from backend.services.exams import exams_bp
from backend.services.admin import admin_bp
from backend.services.enrollment import enrollment_bp
from backend.services.registration_requests import registration_requests_bp
from backend.services.notifications import notifications_bp
from backend.services.users import users_bp
from backend.services.academic_calendar import academic_calendar_bp
from backend.services.academic_rules import academic_rules_bp
from backend.services.instructors import instructors_bp
from backend.services.performance import performance_bp
from backend.api.students_api import students_api_bp

# Core modules
from backend.core.exceptions import register_error_handlers
from backend.core.auth import init_auth
from backend.core.auth import login_required, role_required
from backend.core.logging_config import setup_logging
from backend.core.monitoring import init_monitoring
from backend.core.security import init_security_headers

import os
import pprint
import logging
import importlib
from pathlib import Path

# استخدم مجلد القوالب/الستايتك كما في مشروعك
app = Flask(__name__, template_folder="frontend/templates", static_folder="frontend/static")


@app.route("/static/vendor/webfonts/<path:filename>")
def fontawesome_webfonts_compat(filename):
    """
    توافق مسارات Font Awesome القديمة:
    all.min.css يشير إلى /static/vendor/webfonts/* بينما الملفات الفعلية ضمن
    /static/vendor/fontawesome/webfonts/*
    """
    return send_from_directory("frontend/static/vendor/fontawesome/webfonts", filename)

# إعدادات تطوير محلية لتفادي الحاجة لإعادة تشغيل المنظومة بعد كل تعديل.
if FLASK_ENV != "production":
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    @app.after_request
    def _disable_dev_cache(resp):
        # أثناء التطوير: امنع التخزين المؤقت لملفات الواجهة/HTML حتى تظهر التغييرات فورًا.
        if request.path.startswith("/static/") or "text/html" in (resp.content_type or ""):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
        return resp


@app.after_request
def _disable_grade_drafts_cache(resp):
    """امنَع كاش صفحة مسودات الدرجات دائماً لتفادي ظهور نسخة واجهة قديمة."""
    p = (request.path or "").strip().lower()
    if p.startswith("/grade_drafts") or p.startswith("/grades/drafts"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp

# CSRF protection (Web UI). API routes can be exempted.
app.config.setdefault("WTF_CSRF_HEADERS", ["X-CSRFToken", "X-CSRF-Token"])
csrf = CSRFProtect()
csrf.init_app(app)

# عرض اتصال قاعدة البيانات في الكونسول
tail = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else "(configured)"
print("ACTIVE DATABASE:", ("PostgreSQL — " + tail) if is_postgresql() else tail)

# تهيئة الجداول
ensure_tables()

# إغلاق connection pool عند إيقاف التطبيق
atexit.register(close_pool)

# تهيئة نظام Logging المحسّن
setup_logging(app)

# تهيئة نظام المصادقة
init_auth(app)

# تهيئة نظام Monitoring
init_monitoring(app)

# رؤوس أمان HTTP (CSP في الإنتاج فقط عند تفعيل ENABLE_CSP)
init_security_headers(app)

# تسجيل معالجات الأخطاء
register_error_handlers(app)

# تسجيل الـ Blueprints
app.register_blueprint(students_bp, url_prefix="/students")
app.register_blueprint(courses_bp, url_prefix="/courses")
app.register_blueprint(grades_bp, url_prefix="/grades")
app.register_blueprint(schedule_bp, url_prefix="/schedule")
app.register_blueprint(exams_bp, url_prefix="/exams")
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(enrollment_bp, url_prefix="/enrollment")
app.register_blueprint(registration_requests_bp, url_prefix="/")
app.register_blueprint(notifications_bp, url_prefix="/notifications")
app.register_blueprint(users_bp, url_prefix="/users")
app.register_blueprint(academic_calendar_bp, url_prefix="/academic_calendar")
app.register_blueprint(academic_rules_bp, url_prefix="/academic_rules")
app.register_blueprint(instructors_bp, url_prefix="/instructors")
app.register_blueprint(performance_bp, url_prefix="/performance")
app.register_blueprint(students_api_bp)


def _startup_verify_critical_symbols() -> None:
    """
    فحص مبكر للاستيرادات/الدوال الحرجة حتى لا تظهر أخطاء ImportError وقت الاستخدام.
    """
    checks = [
        ("backend.database.database", "table_to_dicts"),
        ("backend.services.utilities", "get_connection"),
    ]
    missing: list[str] = []
    for module_name, symbol_name in checks:
        try:
            mod = importlib.import_module(module_name)
            if not hasattr(mod, symbol_name):
                missing.append(f"{module_name}.{symbol_name}")
        except Exception:
            missing.append(f"{module_name}.{symbol_name}")
    if missing:
        raise RuntimeError(
            "Startup validation failed. Missing critical symbol(s): " + ", ".join(missing)
        )


_startup_verify_critical_symbols()

# Exempt API blueprints from CSRF (as requested)
try:
    csrf.exempt(students_api_bp)
except Exception:
    pass

# طباعة خريطة المسارات المسجلة (مؤقت للتحقق)
pprint.pprint(sorted([r.rule for r in app.url_map.iter_rules()]))


def _is_instructor_or_supervisor_role() -> bool:
    role = (session.get("user_role") or "").strip()
    if role == "supervisor":
        return True
    if role == "instructor":
        return True
    return False


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """معالج أخطاء CSRF."""
    payload = {
        "success": False,
        "error": "CSRF_FAILED",
        "message": "خطأ أمان: فشل التحقق من CSRF. يرجى إعادة محاولة الطلب.",
    }
    # أغلب واجهات المشروع تستخدم fetch/JSON؛ نرجّع JSON دائماً لتجنب صفحات HTML مكسورة.
    wants_json = request.is_json or "application/json" in (request.headers.get("Accept") or "")
    return (jsonify(payload), 400) if wants_json else (jsonify(payload), 400)

# -----------------------------
# صفحات العرض
# -----------------------------
@app.route("/login")
def login_page():
    """صفحة تسجيل الدخول"""
    return render_template("login.html")

@app.route("/logout")
def logout_page():
    """صفحة تسجيل الخروج - توجيه إلى صفحة تسجيل الدخول"""
    return redirect("/login")

@app.route("/")
@login_required
def index():
    # صفحة البوابة تحتوي "مدخلات الجدولة (JSON)" لذلك تُحجب عن الطالب
    role = session.get("user_role") or ""
    is_supervisor = (role == "supervisor") or (role == "instructor" and int(session.get("is_supervisor") or 0) == 1)
    if role == "student":
        sid = session.get("student_id") or session.get("user")
        return redirect(url_for("student_view", student_id=sid))
    if is_supervisor:
        return redirect(url_for("supervisor_dashboard_page"))
    if role in ("admin", "admin_main", "head_of_department"):
        return redirect(url_for("dashboard_page"))
    if role == "instructor":
        # الأستاذ غير المشرف لا يملك صلاحية dashboard؛ نوجّهه لصفحة السجل الأكاديمي
        return redirect(url_for("transcript_page"))
    return render_template("index.html")

@app.route("/health")
def health():
    """Health check خفيف للـ Docker / LB (بدون ضرب قاعدة البيانات)."""
    from datetime import datetime
    from backend.core.monitoring import app_stats

    return jsonify(
        {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": (datetime.now() - app_stats["start_time"]).total_seconds(),
            "version": (os.environ.get("APP_VERSION") or "2.0.0").strip(),
            "environment": FLASK_ENV,
        }
    ), 200


@app.route("/health/ready")
def health_ready():
    """جاهزية الخدمة مع التحقق من قاعدة البيانات (Kubernetes readiness)."""
    from datetime import datetime

    try:
        from backend.services.utilities import get_connection

        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return jsonify(
            {
                "status": "ready",
                "database_ok": True,
                "timestamp": datetime.now().isoformat(),
            }
        ), 200
    except Exception as e:
        return jsonify(
            {
                "status": "not_ready",
                "database_ok": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }
        ), 503

@app.route("/my_courses")
@login_required
@role_required("instructor")
def my_courses_page():
    """مقرراتي: الشعب المكلَّف بها في الجدول (حسب ربط الحساب بجدول instructors)."""
    return render_template("my_courses.html", active_page="my_courses")


@app.route("/dashboard")
@role_required("admin", "admin_main", "head_of_department")
def dashboard_page():
    return render_template("dashboard.html", active_page="dashboard")


@app.route("/analytics")
@role_required("admin", "admin_main", "head_of_department")
def analytics_dashboard_page():
    # لوحة تحكم تحليلية متقدمة تعتمد على بيانات /performance/report و /admin/summary
    return render_template("analytics_dashboard.html", active_page="analytics")

@app.route("/student_view")
@app.route("/student_view/<student_id>")
@login_required
def student_view(student_id=None):
    return render_template("student_view.html", student_id=student_id)

@app.route("/prereqs_form")
@login_required
@role_required("admin", "admin_main", "head_of_department", "supervisor", "instructor")
def prereqs_form():
    return render_template("prereqs_form.html")


@app.route("/prereqs_flowchart")
@login_required
def prereqs_flowchart_page():
    return render_template("prereqs_flowchart.html")

# ملاحظة: قالب صفحة الطلبة في مشروعك محفوظ باسم students_form.html
@app.route("/students_form")
@login_required
def students_form():
    return render_template("students_form.html")


@app.route("/graduates_page")
@login_required
def graduates_page():
    """صفحة قائمة الخريجين (تحت شؤون الطلبة)."""
    return render_template("graduates.html")

@app.route("/courses_form")
@login_required
@role_required("admin", "admin_main", "head_of_department", "supervisor", "instructor")
def courses_form():
    return render_template("courses_form.html")


@app.route("/instructors_form")
@login_required
def instructors_form():
    # صفحة إدارة أعضاء هيئة التدريس
    if _is_instructor_or_supervisor_role():
        return redirect(url_for("transcript_page"))
    return render_template("instructors_form.html")


@app.route("/supervision_form")
@login_required
def supervision_form():
    # صفحة إسناد الطلبة للمشرفين (للإدارة)
    if _is_instructor_or_supervisor_role():
        return redirect(url_for("transcript_page"))
    return render_template("supervision_form.html")


@app.route("/supervisor_dashboard")
@login_required
def supervisor_dashboard_page():
    # لوحة للمشرفين لعرض طلبتهم وروابط سريعة
    return render_template("supervisor_dashboard.html")

@app.route("/schedule_form")
@role_required("admin", "supervisor", "admin_main", "head_of_department", "instructor")
def schedule_form():
    return render_template("schedule_form.html")


@app.route("/exams/midterms")
@login_required
def exams_midterms():
    return render_template("exams_midterms.html")


@app.route("/exams/finals")
@login_required
def exams_finals():
    return render_template("exams_finals.html")


@app.route("/exams/conflicts")
@login_required
def exams_conflicts():
    return render_template("exams_conflicts.html")

@app.route("/registrations_form")
@login_required
def registrations_form():
    return render_template("registrations_form.html", withdrawn_mode=False)


@app.route("/withdrawn_file_list")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def withdrawn_file_list_page():
    return render_template("registrations_form.html", withdrawn_mode=True)


@app.route("/enrollment_plans")
@login_required
def enrollment_plans_page():
    return render_template("enrollment_plans.html")

@app.route("/notifications_center")
@login_required
def notifications_center_page():
    return render_template("notifications_center.html")

@app.route("/users_admin")
@login_required
@role_required("admin", "admin_main")
def users_admin_page():
    return render_template("users_admin.html")

@app.route("/results")
@login_required
def results_page():
    return render_template("results.html")


@app.route("/attendance_export")
@login_required
@role_required("admin", "admin_main", "head_of_department", "supervisor", "instructor")
def attendance_export_page():
    return render_template("attendance_export.html")

@app.route("/academic_calendar_page")
@login_required
def academic_calendar_page():
    return render_template("academic_calendar.html")


@app.route("/academic_rules_page")
@login_required
def academic_rules_page():
    return render_template("academic_rules.html")

@app.route("/transcript_page")
@login_required
def transcript_page():
    # حل جذري: جهّز قائمة الطلبة + كشف أول طالب (أو المختار) من السيرفر
    from backend.services.utilities import get_connection
    from backend.services.grades import _load_transcript_data

    # جلب الطلبة
    with get_connection() as conn:
        cur = conn.cursor()
        students = cur.execute(
            "SELECT student_id, COALESCE(student_name,'') AS student_name FROM students ORDER BY student_name, student_id"
        ).fetchall()
    students_list = [{"student_id": r[0], "student_name": r[1]} for r in (students or [])]

    selected = (request.args.get("student_id") or "").strip()
    if not selected and students_list:
        selected = students_list[0]["student_id"]

    initial_transcript = None
    if selected:
        try:
            initial_transcript = _load_transcript_data(selected)
        except Exception:
            initial_transcript = None

    return render_template(
        "transcript.html",
        students=students_list,
        selected_student_id=selected,
        initial_transcript=initial_transcript,
    )


@app.route("/grade_drafts")
@login_required
def grade_drafts_page():
    """واجهة مسودات الدرجات: أستاذ (غير مشرف) أو اعتماد من رئيس القسم / الإدارة الرئيسية."""
    role = (session.get("user_role") or "").strip()
    is_sup = (role == "supervisor") or (role == "instructor" and int(session.get("is_supervisor") or 0) == 1)
    has_instructor = bool(session.get("instructor_id"))
    can_instructor_ui = has_instructor and not is_sup and role != "supervisor"
    can_approver_ui = role in ("admin", "admin_main", "head_of_department")
    if can_instructor_ui and can_approver_ui:
        return render_template("grade_drafts.html", page_mode="both", active_page="grade_drafts")
    if can_instructor_ui:
        return render_template("grade_drafts.html", page_mode="instructor", active_page="grade_drafts")
    if can_approver_ui:
        return render_template("grade_drafts.html", page_mode="approver", active_page="grade_drafts")
    return redirect(url_for("transcript_page"))


@app.route("/performance_report")
@login_required
def performance_report_page():
    return render_template("performance_report.html")


@app.route("/registration_requests_page")
@login_required
def registration_requests_page():
    return render_template("registration_requests.html")

@app.route("/electives_report_page")
@login_required
def electives_report_page():
    if _is_instructor_or_supervisor_role():
        return redirect(url_for("performance_report_page"))
    return render_template("electives_report.html")


@app.route("/registration_changes_report_page")
@login_required
def registration_changes_report_page():
    if _is_instructor_or_supervisor_role():
        return redirect(url_for("performance_report_page"))
    return render_template("registration_changes_report.html")


@app.route("/failed_courses_report_page")
@login_required
def failed_courses_report_page():
    if _is_instructor_or_supervisor_role():
        return redirect(url_for("performance_report_page"))
    return render_template("failed_courses_report.html")


@app.route("/uncompleted_courses_report_page")
@login_required
def uncompleted_courses_report_page():
    if _is_instructor_or_supervisor_role():
        return redirect(url_for("performance_report_page"))
    return render_template("uncompleted_courses_report.html")


@app.route("/not_registered_courses_report_page")
@login_required
def not_registered_courses_report_page():
    if _is_instructor_or_supervisor_role():
        return redirect(url_for("performance_report_page"))
    return render_template("not_registered_courses_report.html")


@app.route("/grade_course_mapping_audit_page")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def grade_course_mapping_audit_page():
    return render_template("grade_course_mapping_audit.html")


@app.route("/course_registration_report_page")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def course_registration_report_page():
    """أعداد الطلبة لكل مقرر من التسجيلات الفعلية — للإدارة ورئيس القسم."""
    return render_template("course_registration_report.html")


@app.route("/schedule_versions_page")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def schedule_versions_page():
    """أرشيف نسخ الجدول الدراسي."""
    return render_template("schedule_versions.html")


@app.route("/exam_schedule_versions_page")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def exam_schedule_versions_page():
    """أرشيف نسخ جداول الامتحانات (جزئي / نهائي)."""
    return render_template("exam_versions.html")


@app.route("/course_closure_reports_page")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def course_closure_reports_page():
    """لوحة رئيس القسم لاعتماد تقارير إقفال المقرر."""
    return render_template("course_closure_reports.html")


@app.route("/faculty_scorecards_page")
@login_required
@role_required("admin", "admin_main", "head_of_department", "instructor")
def faculty_scorecards_page():
    """لوحة مؤشرات إنجاز الشعب (Scorecard)."""
    return render_template("faculty_scorecards.html")


@app.route("/faculty_final_dossier_page")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def faculty_final_dossier_page():
    """واجهة الملف النهائي الموحّد للشعب."""
    return render_template("faculty_final_dossier.html")


def _read_text_doc(path: str) -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"File not found: {path}"
        return p.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Failed to read file ({path}): {exc}"


def _is_system_docs_enabled() -> bool:
    """
    تعطيل صفحة توثيق النظام افتراضياً لأسباب أمنية.
    للتفعيل المؤقت: ENABLE_SYSTEM_DOCS_PAGE=1
    """
    v = (os.environ.get("ENABLE_SYSTEM_DOCS_PAGE", "0") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


@app.route("/system_docs")
@role_required("admin_main", "admin")
def system_docs_page():
    if not _is_system_docs_enabled():
        abort(404)
    runbook = _read_text_doc("docs/RUNBOOK.md")
    overview = _read_text_doc("docs/PROJECT_OVERVIEW.md")
    return render_template("system_docs.html", runbook_text=runbook, overview_text=overview)


# -----------------------------
# مسارات توافقية (للحفاظ على عمل الواجهة القديمة)
# -----------------------------
@app.route("/list_students")
@login_required
def compat_list_students():
    return redirect(url_for("students.list_students"))

@app.route("/list_courses")
@login_required
def compat_list_courses():
    return redirect(url_for("courses.list_courses"))

@app.route("/list_prereqs")
@login_required
def compat_list_prereqs():
    return redirect(url_for("courses.list_prereqs"))

@app.route("/list_schedule_rows")
@login_required
def compat_list_schedule_rows():
    return redirect(url_for("schedule.list_schedule_rows"))

@app.route("/results_data")
@login_required
def compat_results_data():
    from backend.database.database import table_to_dicts
    out = {}
    # جدول التعارضات
    try:
        out["conflict_report"] = table_to_dicts("conflict_report")
    except Exception:
        out["conflict_report"] = []
    # جدول التحسينات
    try:
        out["proposed_moves"] = table_to_dicts("proposed_moves")
    except Exception:
        out["proposed_moves"] = []
    # جدول الجدول النهائي: إن كان optimized_schedule فارغاً نعرض schedule لظهور صفوف الجدول
    try:
        out["optimized_schedule"] = table_to_dicts("optimized_schedule")
    except Exception:
        out["optimized_schedule"] = []
    if not out["optimized_schedule"]:
        try:
            schedule_rows = table_to_dicts("schedule")
            out["optimized_schedule"] = [
                {"section_id": i + 1, "course_name": r.get("course_name"), "day": r.get("day"), "time": r.get("time"),
                 "room": r.get("room") or "", "instructor": r.get("instructor") or "", "semester": r.get("semester") or ""}
                for i, r in enumerate(schedule_rows)
                if (r.get("course_name") and r.get("day") and r.get("time"))
            ]
        except Exception:
            pass
    return jsonify(out)

@app.route("/add_student", methods=["POST"])
@login_required
def compat_add_student():
    return redirect(url_for("students.add_student"), code=307)

@app.route("/add_course", methods=["POST"])
@login_required
def compat_add_course():
    return redirect(url_for("courses.add_course"), code=307)

@app.route("/add_schedule_row", methods=["POST"])
@login_required
def compat_add_schedule_row():
    return redirect(url_for("schedule.add_schedule_row"), code=307)


@app.route("/delete_schedule_row", methods=["POST"])
@login_required
def compat_delete_schedule_row():
    return redirect(url_for("schedule.delete_schedule_row"), code=307)


@app.route("/update_schedule_row", methods=["POST"])
@login_required
def compat_update_schedule_row():
    return redirect(url_for("schedule.update_schedule_row"), code=307)

@app.route("/save_registrations", methods=["POST"])
@login_required
def compat_save_registrations():
    return redirect(url_for("students.save_registrations"), code=307)

@app.route("/get_registrations")
@login_required
def compat_get_registrations():
    return redirect(url_for("students.get_registrations"))

@app.route("/delete_registrations", methods=["POST"])
@login_required
def compat_delete_registrations():
    # مسار توافقي لحذف تسجيلات طالب بالكامل
    return redirect(url_for("students.delete_registrations"), code=307)

@app.route("/save_grades", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def compat_save_grades():
    return redirect(url_for("grades.save_grades"), code=307)

@app.route("/transcript/<student_id>")
@login_required
def compat_transcript(student_id):
    return redirect(url_for("grades.get_transcript", student_id=student_id))

@app.route("/update_grade", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def compat_update_grade():
    return redirect(url_for("grades.update_grade"), code=307)

@app.route("/update_course", methods=["POST"])
@login_required
def compat_update_course():
    return redirect(url_for("courses.update_course"), code=307)

@app.route("/delete_student", methods=["POST"])
@login_required
def compat_delete_student():
    return redirect(url_for("students.delete_student"), code=307)

@app.route("/delete_course", methods=["POST"])
@login_required
def compat_delete_course():
    return redirect(url_for("courses.delete_course"), code=307)

@app.route("/run-optimize", methods=["POST"])
@login_required
def compat_run_optimize():
    # No schedule.run_optimize endpoint exists; return a message or handle here
    return jsonify({"error": "Endpoint not implemented. Please implement schedule.run_optimize or use another endpoint."}), 501

@app.route("/proposed_move/<int:section_id>", methods=["POST"])
@login_required
def compat_proposed_move(section_id):
    return redirect(url_for("schedule.proposed_move_action", section_id=section_id), code=307)

# -----------------------------
# توافقية خاصة لمسار إضافة المتطلب القديم
# -----------------------------
# بعض الواجهات القديمة أو قوالبك قد ترْسِل إلى /add_prereq — هذا يسبب 404 لأن الراوت الحقيقي هو /courses/prereqs/add
# هذا الراوت يبقي التوافق ويعيد التوجيه مع الحفاظ على طريقة الطلب (307) حتى يعمل الـ POST كما هو متوقع.
@app.route("/add_prereq", methods=["POST"])
@login_required
def compat_add_prereq():
    return redirect(url_for("courses.add_prereq"), code=307)

# -----------------------------
# تشغيل التطبيق
# -----------------------------
if __name__ == "__main__":
    if FLASK_ENV == "production":
        logging.getLogger(__name__).warning(
            "التشغيل عبر app.run() في الإنتاج غير مُستحسن. استخدم: "
            "gunicorn -w 2 -b 0.0.0.0:5000 wsgi:application"
        )
    app.run(host="0.0.0.0", port=5000, debug=FLASK_DEBUG)
