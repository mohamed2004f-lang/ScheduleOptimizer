from flask import Flask, render_template, redirect, url_for, jsonify
from backend.services.utilities import ensure_tables, DB_FILE

# Blueprints
from backend.services.students import students_bp
from backend.services.courses import courses_bp
from backend.services.grades import grades_bp
from backend.services.schedule import schedule_bp
from backend.services.exams import exams_bp

# Core modules
from backend.core.exceptions import register_error_handlers
from backend.core.auth import init_auth
from backend.core.logging_config import setup_logging
from backend.core.monitoring import init_monitoring

import os
import pprint
import logging

# استخدم مجلد القوالب/الستايتك كما في مشروعك
app = Flask(__name__, template_folder="frontend/templates", static_folder="frontend/static")

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

# طباعة خريطة المسارات المسجلة (مؤقت للتحقق)
pprint.pprint(sorted([r.rule for r in app.url_map.iter_rules()]))

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
def index():
    return render_template("index.html")

@app.route("/health")
def health():
    """Health check endpoint للـ Docker"""
    return jsonify({"status": "healthy"}), 200

@app.route("/dashboard")
def dashboard_page():
    return render_template("dashboard.html")

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

@app.route("/courses_form")
def courses_form():
    return render_template("courses_form.html")

@app.route("/schedule_form")
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

@app.route("/results")
def results_page():
    return render_template("results.html")


@app.route("/attendance_export")
def attendance_export_page():
    return render_template("attendance_export.html")

@app.route("/transcript_page")
def transcript_page():
    return render_template("transcript.html")

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
    # جدول الجدول النهائي
    try:
        out["optimized_schedule"] = table_to_dicts("optimized_schedule")
    except Exception:
        out["optimized_schedule"] = []
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
    app.run(host="127.0.0.1", port=5000, debug=True)
