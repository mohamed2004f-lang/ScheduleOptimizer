from flask import Flask, render_template, redirect, url_for, jsonify, session, request
from flask_wtf.csrf import CSRFProtect, CSRFError
from backend.services.utilities import ensure_tables, DB_FILE

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

import os
import pprint
import logging
from pathlib import Path

# استخدم مجلد القوالب/الستايتك كما في مشروعك
app = Flask(__name__, template_folder="frontend/templates", static_folder="frontend/static")

# CSRF protection (Web UI). API routes can be exempted.
app.config.setdefault("WTF_CSRF_HEADERS", ["X-CSRFToken", "X-CSRF-Token"])
csrf = CSRFProtect()
csrf.init_app(app)

# عرض مسار قاعدة البيانات في الكونسول لمراجعة أنه نفس الملف الذي يحتوي بياناتك
print("Using DB_FILE:", os.path.abspath(DB_FILE))

# فحص سريع: إذا وُجدت أكثر من نسخة من mechanical.db في المشروع، اطبع تحذيراً حتى لا يحدث التباس
dups = []
for dirpath, dirnames, filenames in os.walk(os.path.abspath('.')):
    for fn in filenames:
        if fn.lower() == 'mechanical.db':
            dups.append(os.path.abspath(os.path.join(dirpath, fn)))
if len(dups) > 1:
    print('\nWARNING: Multiple mechanical.db files detected. This can cause stale/missing data in the app.')
    print(' Central DB (should be used):', os.path.abspath(DB_FILE))
    print(' All detected DBs:')
    for p in dups:
        print('  -', p)
    print('Backups of migrated DBs are stored in the backups/ folder. Consider deleting duplicates after verifying data.')

# تهيئة الجداول
ensure_tables()

# تهيئة نظام Logging المحسّن
setup_logging(app)

# تهيئة نظام المصادقة
init_auth(app)

# تهيئة نظام Monitoring
init_monitoring(app)

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

# Exempt API blueprints from CSRF (as requested)
try:
    csrf.exempt(students_api_bp)
except Exception:
    pass

# طباعة خريطة المسارات المسجلة (مؤقت للتحقق)
pprint.pprint(sorted([r.rule for r in app.url_map.iter_rules()]))


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
    if role == "student":
        sid = session.get("student_id") or session.get("user")
        return redirect(url_for("student_view", student_id=sid))
    if role == "supervisor":
        return redirect(url_for("supervisor_dashboard_page"))
    if role != "admin":
        return redirect(url_for("dashboard_page"))
    return render_template("index.html")

@app.route("/health")
def health():
    """Health check endpoint للـ Docker"""
    return jsonify({"status": "healthy"}), 200

@app.route("/dashboard")
@role_required("admin", "supervisor", "admin_main", "head_of_department")
def dashboard_page():
    return render_template("dashboard.html", active_page="dashboard")


@app.route("/analytics")
@role_required("admin", "supervisor", "admin_main", "head_of_department")
def analytics_dashboard_page():
    # لوحة تحكم تحليلية متقدمة تعتمد على بيانات /performance/report و /admin/summary
    return render_template("analytics_dashboard.html", active_page="analytics")

@app.route("/student_view")
@app.route("/student_view/<student_id>")
def student_view(student_id=None):
    return render_template("student_view.html", student_id=student_id)

@app.route("/prereqs_form")
def prereqs_form():
    return render_template("prereqs_form.html")

# ملاحظة: قالب صفحة الطلبة في مشروعك محفوظ باسم students_form.html
@app.route("/students_form")
def students_form():
    return render_template("students_form.html")


@app.route("/graduates_page")
def graduates_page():
    """صفحة قائمة الخريجين (تحت شؤون الطلبة)."""
    return render_template("graduates.html")

@app.route("/courses_form")
def courses_form():
    return render_template("courses_form.html")


@app.route("/instructors_form")
def instructors_form():
    # صفحة إدارة أعضاء هيئة التدريس
    return render_template("instructors_form.html")


@app.route("/supervision_form")
def supervision_form():
    # صفحة إسناد الطلبة للمشرفين (للإدارة)
    return render_template("supervision_form.html")


@app.route("/supervisor_dashboard")
def supervisor_dashboard_page():
    # لوحة للمشرفين لعرض طلبتهم وروابط سريعة
    return render_template("supervisor_dashboard.html")

@app.route("/schedule_form")
@role_required("admin", "supervisor", "admin_main", "head_of_department")
def schedule_form():
    return render_template("schedule_form.html")


@app.route("/exams/midterms")
def exams_midterms():
    return render_template("exams_midterms.html")


@app.route("/exams/finals")
def exams_finals():
    return render_template("exams_finals.html")


@app.route("/exams/conflicts")
def exams_conflicts():
    return render_template("exams_conflicts.html")

@app.route("/registrations_form")
def registrations_form():
    return render_template("registrations_form.html")


@app.route("/enrollment_plans")
def enrollment_plans_page():
    return render_template("enrollment_plans.html")

@app.route("/notifications_center")
def notifications_center_page():
    return render_template("notifications_center.html")

@app.route("/users_admin")
def users_admin_page():
    return render_template("users_admin.html")

@app.route("/results")
def results_page():
    return render_template("results.html")


@app.route("/attendance_export")
def attendance_export_page():
    return render_template("attendance_export.html")

@app.route("/academic_calendar_page")
def academic_calendar_page():
    return render_template("academic_calendar.html")


@app.route("/academic_rules_page")
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


@app.route("/performance_report")
def performance_report_page():
    return render_template("performance_report.html")


@app.route("/registration_requests_page")
def registration_requests_page():
    return render_template("registration_requests.html")

@app.route("/electives_report_page")
def electives_report_page():
    return render_template("electives_report.html")


@app.route("/registration_changes_report_page")
def registration_changes_report_page():
    return render_template("registration_changes_report.html")


@app.route("/failed_courses_report_page")
def failed_courses_report_page():
    return render_template("failed_courses_report.html")


@app.route("/uncompleted_courses_report_page")
def uncompleted_courses_report_page():
    return render_template("uncompleted_courses_report.html")


def _read_text_doc(path: str) -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"File not found: {path}"
        return p.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Failed to read file ({path}): {exc}"


@app.route("/system_docs")
@role_required("admin_main", "admin")
def system_docs_page():
    runbook = _read_text_doc("docs/RUNBOOK.md")
    overview = _read_text_doc("docs/PROJECT_OVERVIEW.md")
    return render_template("system_docs.html", runbook_text=runbook, overview_text=overview)


# -----------------------------
# مسارات توافقية (للحفاظ على عمل الواجهة القديمة)
# -----------------------------
@app.route("/list_students")
def compat_list_students():
    return redirect(url_for("students.list_students"))

@app.route("/list_courses")
def compat_list_courses():
    return redirect(url_for("courses.list_courses"))

@app.route("/list_prereqs")
def compat_list_prereqs():
    return redirect(url_for("courses.list_prereqs"))

@app.route("/list_schedule_rows")
def compat_list_schedule_rows():
    return redirect(url_for("schedule.list_schedule_rows"))

@app.route("/results_data")
def compat_results_data():
    from backend.services.utilities import table_to_dicts
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
def compat_add_student():
    return redirect(url_for("students.add_student"), code=307)

@app.route("/add_course", methods=["POST"])
def compat_add_course():
    return redirect(url_for("courses.add_course"), code=307)

@app.route("/add_schedule_row", methods=["POST"])
def compat_add_schedule_row():
    return redirect(url_for("schedule.add_schedule_row"), code=307)


@app.route("/delete_schedule_row", methods=["POST"])
def compat_delete_schedule_row():
    return redirect(url_for("schedule.delete_schedule_row"), code=307)


@app.route("/update_schedule_row", methods=["POST"])
def compat_update_schedule_row():
    return redirect(url_for("schedule.update_schedule_row"), code=307)

@app.route("/save_registrations", methods=["POST"])
def compat_save_registrations():
    return redirect(url_for("students.save_registrations"), code=307)

@app.route("/get_registrations")
def compat_get_registrations():
    return redirect(url_for("students.get_registrations"))

@app.route("/delete_registrations", methods=["POST"])
def compat_delete_registrations():
    # مسار توافقي لحذف تسجيلات طالب بالكامل
    return redirect(url_for("students.delete_registrations"), code=307)

@app.route("/save_grades", methods=["POST"])
def compat_save_grades():
    return redirect(url_for("grades.save_grades"), code=307)

@app.route("/transcript/<student_id>")
def compat_transcript(student_id):
    return redirect(url_for("grades.get_transcript", student_id=student_id))

@app.route("/update_grade", methods=["POST"])
def compat_update_grade():
    return redirect(url_for("grades.update_grade"), code=307)

@app.route("/update_course", methods=["POST"])
def compat_update_course():
    return redirect(url_for("courses.update_course"), code=307)

@app.route("/delete_student", methods=["POST"])
def compat_delete_student():
    return redirect(url_for("students.delete_student"), code=307)

@app.route("/delete_course", methods=["POST"])
def compat_delete_course():
    return redirect(url_for("courses.delete_course"), code=307)

@app.route("/run-optimize", methods=["POST"])
def compat_run_optimize():
    # No schedule.run_optimize endpoint exists; return a message or handle here
    return jsonify({"error": "Endpoint not implemented. Please implement schedule.run_optimize or use another endpoint."}), 501

@app.route("/proposed_move/<int:section_id>", methods=["POST"])
def compat_proposed_move(section_id):
    return redirect(url_for("schedule.proposed_move_action", section_id=section_id), code=307)

# -----------------------------
# توافقية خاصة لمسار إضافة المتطلب القديم
# -----------------------------
# بعض الواجهات القديمة أو قوالبك قد ترْسِل إلى /add_prereq — هذا يسبب 404 لأن الراوت الحقيقي هو /courses/prereqs/add
# هذا الراوت يبقي التوافق ويعيد التوجيه مع الحفاظ على طريقة الطلب (307) حتى يعمل الـ POST كما هو متوقع.
@app.route("/add_prereq", methods=["POST"])
def compat_add_prereq():
    return redirect(url_for("courses.add_prereq"), code=307)

# -----------------------------
# تشغيل التطبيق
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
