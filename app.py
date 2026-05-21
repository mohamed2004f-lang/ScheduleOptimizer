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
from backend.services.course_equivalences import course_equivalence_bp
from backend.services.department_policies import department_policies_bp
from backend.services.college_catalog import college_catalog_bp
from backend.services.performance import performance_bp
from backend.api.students_api import students_api_bp
from backend.services.index_portal import index_portal_bp
from backend.services.academic_quality import academic_quality_bp
from backend.services.course_evaluations import course_evaluations_bp
from backend.services.learning_outcomes import learning_outcomes_bp

# Core modules
from backend.core.exceptions import register_error_handlers
from backend.core.auth import init_auth
from backend.core.auth import (
    login_required,
    role_required,
    current_supervisor_effective,
    SESSION_ACTIVE_MODE,
    _normalize_role,
    get_admin_department_scope_id,
)
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
def _no_cache_html_responses(resp):
    """منع كاش صفحات HTML في كل البيئات حتى تظهر تحديثات القوالب فوراً (خاصة الإنتاج خلف CDN/بروكسي)."""
    ct = resp.content_type or ""
    if "text/html" in ct:
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

# تخزين مؤقت للقوائم (Flask-Caching — SimpleCache أو Redis)
try:
    from backend.core.cache_setup import init_app_cache

    init_app_cache(app)
except Exception as _cache_exc:
    logging.getLogger(__name__).warning("Flask-Caching init skipped: %s", _cache_exc)

# تهيئة نظام المصادقة
init_auth(app)

# إعفاء تبديل وضع العمل (fetch JSON) من CSRF — يُكمّل csrf.exempt داخل init_auth إن وُجد
try:
    _am = app.view_functions.get("auth.set_active_mode")
    if _am is not None:
        csrf.exempt(_am)
    _ads = app.view_functions.get("auth.set_admin_department_scope")
    if _ads is not None:
        csrf.exempt(_ads)
except Exception:
    pass

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
app.register_blueprint(course_equivalence_bp)
app.register_blueprint(department_policies_bp)
from backend.services.pathway_regulations import register_pathway_regulation_routes

register_pathway_regulation_routes(college_catalog_bp)
app.register_blueprint(college_catalog_bp)
app.register_blueprint(performance_bp, url_prefix="/performance")
app.register_blueprint(students_api_bp)
app.register_blueprint(index_portal_bp, url_prefix="/index")
app.register_blueprint(academic_quality_bp, url_prefix="/academic_quality")
app.register_blueprint(learning_outcomes_bp, url_prefix="/academic_quality/ilo")
app.register_blueprint(course_evaluations_bp, url_prefix="/students/evaluations")


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


def _resolve_actor_department_id(conn) -> int | None:
    """استنتاج قسم المستخدم الحالي (users.department_id ثم instructors.department_id)."""
    cur = conn.cursor()
    uname = (session.get("user") or session.get("username") or "").strip()
    if uname:
        try:
            row = cur.execute(
                "SELECT department_id FROM users WHERE lower(username)=lower(?) LIMIT 1",
                (uname,),
            ).fetchone()
            if row and row[0] not in (None, ""):
                return int(row[0])
        except Exception:
            pass
    try:
        iid = int(session.get("instructor_id") or 0)
    except (TypeError, ValueError):
        iid = 0
    if iid:
        try:
            row = cur.execute(
                "SELECT department_id FROM instructors WHERE id = ? LIMIT 1",
                (iid,),
            ).fetchone()
            if row and row[0] not in (None, ""):
                return int(row[0])
        except Exception:
            pass
    return None


@app.context_processor
def inject_ui_context():
    """
    سياق واجهة موحد للهوية أعلى الشريط:
    كلية ثابتة + قسم/نطاق ديناميكي.
    """
    ctx = {
        "college_name_ar": "كلية الهندسة",
        "university_name_ar": "جامعة درنة",
        "department_name_ar": "كل الأقسام",
        "department_scope_label_ar": "نطاق العرض: كل الأقسام",
        "actor_display_ar": "",
    }
    try:
        role_n = _normalize_role((session.get("user_role") or "").strip())
        active_mode = (session.get(SESSION_ACTIVE_MODE) or "").strip().lower()
        uname = (session.get("user") or session.get("username") or "").strip()
        from backend.services.utilities import get_connection

        dep_id = None
        student_identity_label = False
        with get_connection() as conn:
            cur = conn.cursor()
            if role_n == "student":
                from backend.core.department_scope_policy import resolve_student_department_id

                sid_for_dept = (session.get("student_id") or uname or "").strip()
                dep_id = resolve_student_department_id(conn, sid_for_dept)
                student_identity_label = dep_id is not None
            elif role_n in ("admin", "admin_main"):
                dep_id = get_admin_department_scope_id()
            elif role_n == "head_of_department":
                if active_mode in ("", "head", "hod", "department_head"):
                    dep_id = _resolve_actor_department_id(conn)
            elif role_n in ("instructor", "supervisor"):
                dep_id = _resolve_actor_department_id(conn)

            if dep_id is not None:
                row = cur.execute(
                    "SELECT code, name_ar FROM departments WHERE id = ? LIMIT 1",
                    (int(dep_id),),
                ).fetchone()
                if row:
                    code = (row[0] or "").strip()
                    name_ar = (row[1] or "").strip() or "قسم غير معرّف"
                    display = f"{name_ar}" + (f" ({code})" if code else "")
                    ctx["department_name_ar"] = display
                    if student_identity_label:
                        ctx["department_scope_label_ar"] = f"القسم: {display}"
                    else:
                        ctx["department_scope_label_ar"] = f"نطاق العرض: {display}"

            # سطر تعريف واضح بالمستخدم الداخل (حسب الدور/الوضع)
            display_actor = ""
            if role_n == "student":
                sid = (session.get("student_id") or uname or "").strip()
                srow = cur.execute(
                    "SELECT COALESCE(student_name,'') FROM students WHERE student_id = ? LIMIT 1",
                    (sid,),
                ).fetchone()
                sname = ((srow[0] if srow else "") or "").strip()
                who = f"{sname} {sid}".strip() if sname else sid
                if who:
                    display_actor = f"طالب {who}"
            elif role_n == "head_of_department" and active_mode in ("", "head", "hod", "department_head"):
                # اسم رئيس القسم: من اسم الأستاذ المرتبط إن وُجد، وإلا username.
                irow = cur.execute(
                    """
                    SELECT COALESCE(i.name,'')
                    FROM users u
                    LEFT JOIN instructors i ON i.id = u.instructor_id
                    WHERE lower(u.username)=lower(?)
                    LIMIT 1
                    """,
                    (uname,),
                ).fetchone()
                nm = ((irow[0] if irow else "") or "").strip() or uname
                if nm:
                    display_actor = f"رئيس قسم - {nm}"
            else:
                # أستاذ/مشرف أو رئيس قسم في وضع أستاذ/مشرف
                eff_mode = active_mode
                if role_n == "head_of_department":
                    if eff_mode not in ("instructor", "supervisor"):
                        eff_mode = "head"
                iid_raw = session.get("instructor_id")
                try:
                    iid = int(iid_raw or 0)
                except (TypeError, ValueError):
                    iid = 0
                iname = ""
                if iid:
                    irow = cur.execute(
                        "SELECT COALESCE(name,'') FROM instructors WHERE id = ? LIMIT 1",
                        (iid,),
                    ).fetchone()
                    iname = ((irow[0] if irow else "") or "").strip()
                if not iname and uname:
                    irow2 = cur.execute(
                        """
                        SELECT COALESCE(i.name,'')
                        FROM users u
                        LEFT JOIN instructors i ON i.id = u.instructor_id
                        WHERE lower(u.username)=lower(?)
                        LIMIT 1
                        """,
                        (uname,),
                    ).fetchone()
                    iname = ((irow2[0] if irow2 else "") or "").strip()
                if iname:
                    if role_n == "supervisor" or eff_mode == "supervisor":
                        display_actor = f"مشرف أكاديمي - {iname}"
                    elif role_n == "instructor" or eff_mode == "instructor":
                        display_actor = f"أستاذ/ة {iname}"
                if not display_actor and uname:
                    if role_n in ("admin", "admin_main"):
                        display_actor = f"إدارة النظام - {uname}"
                    elif role_n == "head_of_department":
                        display_actor = f"رئيس قسم - {uname}"
                    elif role_n == "supervisor":
                        display_actor = f"مشرف أكاديمي - {uname}"
                    elif role_n == "instructor":
                        display_actor = f"أستاذ/ة {uname}"
                    else:
                        display_actor = uname
            ctx["actor_display_ar"] = display_actor
    except Exception:
        pass
    return {"ui_context": ctx}


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
    if role == "head_of_department":
        am = (session.get(SESSION_ACTIVE_MODE) or "head").strip().lower()
        if am == "instructor" and session.get("instructor_id"):
            return redirect(url_for("my_courses_page"))
    if current_supervisor_effective():
        return redirect(url_for("supervisor_dashboard_page"))
    if role in ("admin", "admin_main", "head_of_department"):
        return redirect(url_for("dashboard_page"))
    if role == "instructor":
        # الأستاذ غير المشرف: نقطة الدخول «مقرراتي» (وليس كشف درجات الطلبة)
        return redirect(url_for("my_courses_page"))
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
@role_required("admin", "admin_main", "head_of_department", "supervisor")
def prereqs_form():
    return render_template("prereqs_form.html")


@app.route("/prereqs_flowchart")
@login_required
@role_required("admin", "admin_main", "head_of_department", "supervisor")
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
    if not current_supervisor_effective():
        return redirect(url_for("my_courses_page"))
    return render_template("supervisor_dashboard.html")

@app.route("/schedule_form")
@role_required("admin", "supervisor", "admin_main", "head_of_department", "instructor", "student")
def schedule_form():
    return render_template("schedule_form.html")


@app.route("/exams/midterms")
@login_required
def exams_midterms():
    return render_template("exams_schedule.html", initial_exam_type="midterm")


@app.route("/exams/finals")
@login_required
def exams_finals():
    return render_template("exams_schedule.html", initial_exam_type="final")


@app.route("/exams/schedule")
@login_required
def exams_schedule_unified():
    t = (request.args.get("type") or "midterm").strip().lower()
    if t not in ("midterm", "final"):
        t = "midterm"
    return render_template("exams_schedule.html", initial_exam_type=t)


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
@role_required("admin", "admin_main", "head_of_department")
def academic_rules_page():
    return render_template("academic_rules.html")


@app.route("/college_catalog_page")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def college_catalog_page():
    return render_template("college_catalog.html")


@app.route("/course_equivalences_page")
@login_required
@role_required("admin", "admin_main")
def course_equivalences_page():
    return render_template("course_equivalences.html")


@app.route("/department_policy_head_page")
@login_required
@role_required("head_of_department")
def department_policy_head_page():
    return render_template("department_policy_head.html")


@app.route("/department_policy_approvals_page")
@login_required
@role_required("admin_main")
def department_policy_approvals_page():
    return render_template("department_policy_approvals.html")


@app.route("/transcript_page")
@login_required
def transcript_page():
    role = (session.get("user_role") or "").strip()
    active_m = (session.get(SESSION_ACTIVE_MODE) or "").strip().lower()
    if (role == "instructor" and not current_supervisor_effective()) or (
        role == "head_of_department" and active_m == "instructor"
    ):
        return redirect(url_for("my_courses_page"))

    # حل جذري: جهّز قائمة الطلبة + كشف أول طالب (أو المختار) من السيرفر
    from backend.services.utilities import get_connection
    from backend.services.grades import _load_transcript_data
    from backend.services.students import _get_allowed_student_ids_for_role, normalize_sid
    from backend.core.department_scope_policy import resolve_scope_sql_for_students_table

    with get_connection() as conn:
        cur = conn.cursor()
        username = (session.get("user") or session.get("username") or "").strip()
        allowed_ids = _get_allowed_student_ids_for_role(conn, role)
        scope_sql, scope_params = resolve_scope_sql_for_students_table(conn, username)

        base_q = "SELECT student_id, COALESCE(student_name,'') AS student_name FROM students"
        where_parts = []
        params: list = []
        if scope_sql == "1=0":
            students = []
        else:
            if scope_sql:
                where_parts.append(f"({scope_sql})")
                params.extend(list(scope_params or ()))
            if allowed_ids is not None:
                if not allowed_ids:
                    students = []
                else:
                    placeholders = ",".join("?" for _ in allowed_ids)
                    where_parts.append(f"student_id IN ({placeholders})")
                    params.extend(list(allowed_ids))
            if "students" not in locals():
                q = base_q
                if where_parts:
                    q += " WHERE " + " AND ".join(where_parts)
                q += " ORDER BY student_name, student_id"
                students = cur.execute(q, tuple(params)).fetchall()

    students_list = [{"student_id": r[0], "student_name": r[1]} for r in (students or []) if r and r[0]]

    selected = (request.args.get("student_id") or "").strip()
    if selected:
        selected = normalize_sid(selected)
    allowed_id_set = {normalize_sid(s["student_id"]) for s in students_list}
    if selected and selected not in allowed_id_set:
        selected = ""
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
    try:
        db_sup = int(session.get("is_supervisor") or 0) == 1
    except (TypeError, ValueError):
        db_sup = False
    if role == "head_of_department":
        active_m = (session.get(SESSION_ACTIVE_MODE) or "head").strip().lower()
    else:
        active_m = (session.get(SESSION_ACTIVE_MODE) or "instructor").strip().lower()
    has_instructor = bool(session.get("instructor_id"))
    can_instructor_ui = has_instructor and (
        (role == "instructor" and (not db_sup or active_m == "instructor"))
        or (role == "head_of_department" and active_m == "instructor")
    )
    can_approver_ui = role in ("admin", "admin_main") or (
        role == "head_of_department"
        and active_m in ("", "head", "hod", "department_head")
    )
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
    role = (session.get("user_role") or "").strip()
    active_m = (session.get(SESSION_ACTIVE_MODE) or "").strip().lower()
    if role == "instructor" and not current_supervisor_effective():
        return redirect(url_for("my_courses_page"))
    if role == "head_of_department" and active_m == "instructor":
        return redirect(url_for("my_courses_page"))
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


@app.route("/academic_quality_dashboard_page")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def academic_quality_dashboard_page():
    """لوحة ضمان الجودة والاعتماد الأكاديمي."""
    return redirect(url_for("academic_quality.quality_dashboard"))


@app.route("/ilo_catalog_page")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def ilo_catalog_page_redirect():
    return redirect(url_for("learning_outcomes.ilo_catalog_page"))


@app.route("/supervisor_quality_report_page")
@login_required
def supervisor_quality_report_page_redirect():
    return redirect(url_for("academic_quality.supervisor_report_page"))


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
    """
    نتائج التعارضات والجدول للعرض (لوحة النتائج، لوحة القيادة، إلخ).
    عند نطاق قسم (رئيس قسم / مسؤول بقسم معيّن): يُقصّ conflict_report و optimized_schedule
    كي لا تُعرض بيانات أقسام أخرى.
    """
    from backend.database.database import get_connection, fetch_table_columns, table_exists
    from backend.core.auth import _normalize_role
    from backend.core import department_scope_policy as dsp
    from backend.services.schedule import _effective_schedule_department_scope_id, _load_schedule_rows_for_export

    out = {"conflict_report": [], "proposed_moves": [], "optimized_schedule": []}
    username = (session.get("user") or session.get("username") or "").strip()

    with get_connection() as conn:
        cur = conn.cursor()
        role_n = _normalize_role((session.get("user_role") or "").strip())
        list_mode, _list_dept = dsp.resolve_users_list_scope(conn, username)
        scope_st_sql, scope_st_params = dsp.resolve_scope_sql_for_aliased_student(conn, username, "st")

        # --- تعارضات الجدول (مرتبطة بطالب) ---
        try:
            if table_exists(conn, "conflict_report"):
                if scope_st_sql == "1=0":
                    out["conflict_report"] = []
                elif scope_st_sql:
                    rows = cur.execute(
                        f"""
                        SELECT cr.*
                        FROM conflict_report cr
                        INNER JOIN students st ON st.student_id = cr.student_id
                        WHERE ({scope_st_sql})
                        """,
                        scope_st_params,
                    ).fetchall()
                    out["conflict_report"] = [dict(r) for r in rows]
                else:
                    rows = cur.execute("SELECT * FROM conflict_report").fetchall()
                    out["conflict_report"] = [dict(r) for r in rows]
        except Exception:
            out["conflict_report"] = []

        # --- proposed_moves: لا نطابقها بقسم بسهولة؛ نخفيها عند نطاق قسم تجنباً لإرباك/تسريب ---
        try:
            if table_exists(conn, "proposed_moves"):
                if list_mode in ("department", "empty"):
                    out["proposed_moves"] = []
                else:
                    rows = cur.execute("SELECT * FROM proposed_moves").fetchall()
                    out["proposed_moves"] = [dict(r) for r in rows]
        except Exception:
            out["proposed_moves"] = []

        # --- الجدول المعروض (optimized أو صفوف schedule) ---
        sched_scope = _effective_schedule_department_scope_id(conn)
        scoped_ui = sched_scope is not None and role_n in ("admin", "admin_main", "head_of_department")
        cols_courses = fetch_table_columns(conn, "courses") if table_exists(conn, "courses") else []
        has_owning_course = "owning_department_id" in cols_courses
        cols_sched = fetch_table_columns(conn, "schedule") if table_exists(conn, "schedule") else []
        sched_has_dept = "department_id" in cols_sched

        try:
            opt_tbl = []
            if table_exists(conn, "optimized_schedule"):
                opt_tbl = [dict(r) for r in cur.execute("SELECT * FROM optimized_schedule").fetchall()]

            final_opt = []
            if opt_tbl:
                if scoped_ui and sched_scope is not None:
                    if has_owning_course:
                        scoped_rows = cur.execute(
                            """
                            SELECT os.*
                            FROM optimized_schedule os
                            INNER JOIN courses c ON c.course_name = os.course_name
                            WHERE COALESCE(os.course_name, '') <> ''
                              AND COALESCE(os.day, '') <> ''
                              AND COALESCE(os.time, '') <> ''
                              AND COALESCE(c.owning_department_id, -1) = ?
                            """,
                            (int(sched_scope),),
                        ).fetchall()
                        final_opt = [dict(r) for r in scoped_rows]
                    elif sched_has_dept:
                        allowed_names = {
                            (r[0] or "").strip()
                            for r in cur.execute(
                                """
                                SELECT DISTINCT course_name FROM schedule
                                WHERE COALESCE(course_name, '') <> ''
                                  AND COALESCE(day, '') <> ''
                                  AND COALESCE(time, '') <> ''
                                  AND department_id = ?
                                """,
                                (int(sched_scope),),
                            ).fetchall()
                        }
                        final_opt = [
                            r
                            for r in opt_tbl
                            if (r.get("course_name") or "").strip() in allowed_names
                            and (r.get("course_name") and r.get("day") and r.get("time"))
                        ]
                    else:
                        final_opt = []
                else:
                    final_opt = opt_tbl
            else:
                schedule_dicts = _load_schedule_rows_for_export(conn)
                final_opt = [
                    {
                        "section_id": i + 1,
                        "course_name": r.get("course_name"),
                        "day": r.get("day"),
                        "time": r.get("time"),
                        "room": r.get("room") or "",
                        "instructor": r.get("instructor") or "",
                        "semester": r.get("semester") or "",
                    }
                    for i, r in enumerate(schedule_dicts)
                    if (r.get("course_name") and r.get("day") and r.get("time"))
                ]
            out["optimized_schedule"] = final_opt
        except Exception:
            out["optimized_schedule"] = []

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

@app.route("/submit-data", methods=["POST"])
@login_required
def submit_data():
    """حفظ دفعة بيانات الجدولة من صفحة index (JSON)."""
    from backend.core.services import StudentService, ScheduleService
    from backend.core.exceptions import ValidationError, AppException
    from backend.core.validators import (
        validate_course_name,
        validate_schedule_row_dict,
        validate_student_id,
    )
    from collections import defaultdict

    data = request.get_json(force=True) or {}
    students = data.get("students") or []
    schedule = data.get("schedule") or []
    registrations = data.get("registrations") or []
    stats = {"students": 0, "schedule": 0, "registrations": 0}
    errors = []

    for row in students:
        try:
            sid = (row.get("student_id") or "").strip()
            if not sid:
                continue
            ok_sid, sid_err = validate_student_id(sid)
            if not ok_sid:
                errors.append(f"طالب {sid}: {sid_err}")
                continue
            StudentService.add_student(
                sid,
                (row.get("student_name") or "").strip(),
            )
            stats["students"] += 1
        except (ValidationError, AppException) as e:
            errors.append(f"طالب {row.get('student_id')}: {e}")
        except Exception as e:
            errors.append(f"طالب {row.get('student_id')}: {e}")

    for row in schedule:
        try:
            if not row.get("course_name") or not row.get("day") or not row.get("time"):
                continue
            ok_row, row_err = validate_schedule_row_dict(row)
            if not ok_row:
                errors.append(f"جدول {row.get('course_name')}: {row_err}")
                continue
            ScheduleService.add_schedule_row(
                row.get("course_name"),
                row.get("day"),
                row.get("time"),
                room=row.get("room", ""),
                instructor=row.get("instructor", ""),
                semester=(row.get("semester") or "").strip(),
            )
            stats["schedule"] += 1
        except (ValidationError, AppException) as e:
            errors.append(f"جدول {row.get('course_name')}: {e}")
        except Exception as e:
            errors.append(f"جدول {row.get('course_name')}: {e}")

    by_student = defaultdict(list)
    for row in registrations:
        sid = (row.get("student_id") or "").strip()
        cname = (row.get("course_name") or "").strip()
        if sid and cname:
            ok_sid, _ = validate_student_id(sid)
            ok_c, _ = validate_course_name(cname)
            if ok_sid and ok_c:
                by_student[sid].append(cname)
            else:
                errors.append(f"تسجيل {sid}/{cname}: بيانات غير صالحة")

    for sid, courses in by_student.items():
        try:
            from backend.core.services import StudentService as _SS

            _SS.save_registrations(sid, courses)
            stats["registrations"] += len(courses)
        except (ValidationError, AppException) as e:
            errors.append(f"تسجيل {sid}: {e}")
        except Exception as e:
            errors.append(f"تسجيل {sid}: {e}")

    if errors and not any(stats.values()):
        return jsonify({"status": "error", "message": errors[0], "errors": errors[:5]}), 400
    return jsonify({
        "status": "ok",
        "message": "تم حفظ البيانات",
        "stats": stats,
        "errors": errors[:10] if errors else [],
    }), 200


@app.route("/run-optimize", methods=["POST"])
@login_required
def compat_run_optimize():
    from backend.services.schedule import run_optimize

    return run_optimize()

@app.route("/proposed_move/<int:section_id>", methods=["POST"])
@login_required
def compat_proposed_move(section_id):
    from backend.services.schedule import proposed_move_action

    return proposed_move_action(section_id)

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
