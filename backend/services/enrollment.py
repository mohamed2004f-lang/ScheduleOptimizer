import datetime
import os
import subprocess
import sys
import tempfile

from flask import Blueprint, request, jsonify, session, send_file, abort, current_app, render_template

from backend.core.auth import login_required, role_required, SUPERVISOR_USERNAME, ADMIN_USERNAME
from .utilities import get_connection, log_activity, create_notification
from backend.services.grades import _load_transcript_data

DocxTemplate = None


def _ensure_docxtpl():
    """استيراد docxtpl؛ إن فشل، تثبيتها تلقائياً في بيئة التشغيل الحالية ثم إعادة المحاولة."""
    global DocxTemplate
    if DocxTemplate is not None:
        return True
    try:
        from docxtpl import DocxTemplate as _DT
        DocxTemplate = _DT  # noqa: F811
        return True
    except ImportError:
        pass
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "docxtpl"],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except Exception:
        pass
    try:
        from docxtpl import DocxTemplate as _DT
        DocxTemplate = _DT  # noqa: F811
        return True
    except ImportError:
        return False


# محاولة التحميل عند استيراد الموديول (مرة واحدة عند تشغيل التطبيق)
_ensure_docxtpl()

enrollment_bp = Blueprint("enrollment", __name__)


def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat()


def _classify_status_from_gpa(gpa: float) -> str:
    try:
        g = float(gpa or 0)
    except Exception:
        g = 0.0
    if g >= 85:
        return "ممتاز"
    elif g >= 75:
        return "جيد جداً"
    elif g >= 65:
        return "جيد"
    elif g >= 50:
        return "مقبول"
    else:
        return "ضعيف"


def _compute_units_for_courses(cur, courses: list[str]) -> tuple[int, bool]:
    """
    Return (total_units, has_special_unit_course) for the given course names.
    Special unit courses are those with units == 1 or units == 4.
    """
    if not courses:
        return 0, False
    # إزالة التكرار للحماية من تضخيم المجموع
    uniq = []
    seen = set()
    for c in courses:
        c = (c or "").strip()
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)

    placeholders = ",".join(["?"] * len(uniq))
    rows = cur.execute(
        f"SELECT course_name, COALESCE(units, 0) AS units FROM courses WHERE course_name IN ({placeholders})",
        uniq,
    ).fetchall()
    units_map = {}
    for r in rows:
        try:
            name = r[0]
            units_val = int(r[1] or 0)
        except Exception:
            continue
        units_map[name] = units_val

    total = 0
    has_special = False
    for name in uniq:
        u = int(units_map.get(name, 0) or 0)
        total += u
        if u in (1, 4):
            has_special = True
    return int(total), bool(has_special)


def _max_units_allowed(cumulative_gpa: float, has_special_unit_course: bool) -> int:
    """
    Rules:
      - If cumulative_gpa < 75: max 18, or 19 if any selected course has units 1 or 4
      - If cumulative_gpa >= 75: max 21, or 22 if any selected course has units 1 or 4
    """
    try:
        g = float(cumulative_gpa or 0)
    except Exception:
        g = 0.0
    base = 21 if g >= 75.0 else 18
    return int(base + (1 if has_special_unit_course else 0))


def _enforce_units_limit(cur, student_id: str, courses: list[str]):
    """
    Raises ValueError with Arabic message if units exceed allowed cap.
    """
    transcript = _load_transcript_data(student_id)
    try:
        cumulative_gpa = float(transcript.get("cumulative_gpa") or 0.0)
    except Exception:
        cumulative_gpa = 0.0
    total_units, has_special = _compute_units_for_courses(cur, courses)
    max_allowed = _max_units_allowed(cumulative_gpa, has_special)
    if total_units > max_allowed:
        extra = total_units - max_allowed
        raise ValueError(
            f"لا يمكن حفظ/إرسال الخطة لأن مجموع الوحدات ({total_units}) يتجاوز الحد المسموح ({max_allowed}) "
            f"حسب المعدل التراكمي ({cumulative_gpa:.2f}). الرجاء إزالة {extra} وحدة/وحدات."
        )


def _build_registration_form_context(student_id: str, semester_param: str, source: str = "plan"):
    student_id = (student_id or "").strip()
    semester_param = (semester_param or "").strip()
    source = (source or "plan").strip().lower()
    if source not in ("plan", "actual"):
        source = "plan"

    with get_connection() as conn:
        cur = conn.cursor()
        cols = [row[1] for row in cur.execute("PRAGMA table_info(students)").fetchall()]
        has_uni = "university_number" in cols

        # بيانات الطالب الأساسية (university_number قد لا يكون موجوداً في بعض القواعد)
        if has_uni:
            st = cur.execute(
                """
                SELECT student_id,
                       COALESCE(student_name, '') AS student_name,
                       COALESCE(university_number, '') AS university_number
                FROM students WHERE student_id = ?
                """,
                (student_id,),
            ).fetchone()
        else:
            st = cur.execute(
                """
                SELECT student_id,
                       COALESCE(student_name, '') AS student_name,
                       '' AS university_number
                FROM students WHERE student_id = ?
                """,
                (student_id,),
            ).fetchone()
        if not st:
            abort(404)
        sid, sname, uni = st[0], st[1], st[2]

        # اختيار مصدر المقررات:
        # - plan: من آخر خطة معتمدة (السلوك الحالي)
        # - actual: من جدول registrations الفعلي مباشرة
        row = None
        if source == "plan":
            if semester_param:
                row = cur.execute(
                    """
                    SELECT id, semester
                    FROM enrollment_plans
                    WHERE student_id = ? AND semester = ? AND status = 'Approved'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (sid, semester_param),
                ).fetchone()

            if not row:
                row = cur.execute(
                    """
                    SELECT id, semester
                    FROM enrollment_plans
                    WHERE student_id = ? AND status = 'Approved'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (sid,),
                ).fetchone()

        courses_rows = []
        semester_label = semester_param or ""

        if source == "plan" and row:
            plan_id, semester_label = row
            courses_rows = cur.execute(
                """
                SELECT i.course_name,
                       COALESCE(c.course_code, '') AS course_code,
                       COALESCE(c.units, 0)        AS units
                FROM enrollment_plan_items i
                LEFT JOIN courses c ON i.course_name = c.course_name
                WHERE i.plan_id = ?
                ORDER BY i.course_name
                """,
                (plan_id,),
            ).fetchall()
        else:
            # source=actual أو لا توجد خطة معتمدة: نستخدم جدول registrations
            courses_rows = cur.execute(
                """
                SELECT r.course_name,
                       COALESCE(c.course_code, '') AS course_code,
                       COALESCE(c.units, 0)        AS units
                FROM registrations r
                LEFT JOIN courses c ON r.course_name = c.course_name
                WHERE r.student_id = ?
                ORDER BY r.course_name
                """,
                (sid,),
            ).fetchall()

        courses = []
        total_units = 0
        idx = 1
        for name, code, units in courses_rows:
            units_int = int(units or 0)
            total_units += units_int
            courses.append(
                {
                    "index": idx,
                    "name": name or "",
                    "code": code or "",
                    "units": units_int or "",
                    "notes": "",
                }
            )
            idx += 1

        # إكمال الجدول حتى 10 صفوف
        while len(courses) < 10:
            courses.append(
                {
                    "index": len(courses) + 1,
                    "name": "",
                    "code": "",
                    "units": "",
                    "notes": "",
                }
            )

    # بيانات المعدل والوحدات المنجزة
    transcript = _load_transcript_data(sid)
    completed_units = int(transcript.get("completed_units") or 0)
    cumulative_gpa = float(transcript.get("cumulative_gpa") or 0.0)
    status = _classify_status_from_gpa(cumulative_gpa)

    context = {
        "department": "الهندسة الميكانيكية",
        "student_name": sname,
        "student_id": sid,
        "university_number": uni,
        "academic_year": "",
        "semester": semester_label,
        "completed_units": completed_units,
        "cumulative_gpa": f"{cumulative_gpa:.2f}",
        "status": status,
        "total_units": total_units,
        "courses": courses,
    }
    return context


@enrollment_bp.route("/plans", methods=["GET"])
@login_required
def list_plans():
    """
    إرجاع خطط التسجيل لطالب معيّن (أو لجميع الطلبة).
    query params:
      - student_id (اختياري)
      - semester (اختياري)
    """
    student_id = (request.args.get("student_id") or "").strip()
    semester = (request.args.get("semester") or "").strip()
    include_archived = (request.args.get("include_archived") or "").strip() == "1"

    # الطالب لا يمكنه رؤية إلا خططه هو
    user_role = session.get("user_role")
    if user_role == "student":
        sid_session = session.get("student_id") or session.get("user")
        student_id = sid_session
    # المشرف لا يمكنه رؤية إلا خطط الطلبة المسندين إليه
    if user_role == "supervisor":
        instructor_id = session.get("instructor_id")
        if not instructor_id:
            return jsonify({"status": "error", "message": "لا يوجد ربط بين هذا الحساب وعضو هيئة تدريس", "code": "FORBIDDEN"}), 403


    with get_connection() as conn:
        cur = conn.cursor()
        q = "SELECT id, student_id, semester, status, rejection_reason, created_at, updated_at FROM enrollment_plans WHERE 1=1"
        params = []
        if student_id:
            q += " AND student_id = ?"
            params.append(student_id)
        elif user_role == "supervisor":
            # تقييد الخطط على الطلبة المسندين لهذا المشرف
            q += " AND student_id IN (SELECT student_id FROM student_supervisor WHERE instructor_id = ?)"
            params.append(instructor_id)
        if semester:
            q += " AND semester = ?"
            params.append(semester)
        if not include_archived:
            q += " AND status != 'Archived'"
        q += " ORDER BY created_at DESC, id DESC"
        rows = cur.execute(q, params).fetchall()

        plans = []
        for r in rows:
            plan_id = r[0]
            items = cur.execute(
                "SELECT id, course_name FROM enrollment_plan_items WHERE plan_id = ? ORDER BY id",
                (plan_id,),
            ).fetchall()
            plans.append(
                {
                    "id": plan_id,
                    "student_id": r[1],
                    "semester": r[2],
                    "status": r[3],
                    "rejection_reason": r[4],
                    "created_at": r[5],
                    "updated_at": r[6],
                    "courses": [it[1] for it in items],
                }
            )

    return jsonify({"status": "ok", "plans": plans})


@enrollment_bp.route("/plans", methods=["POST"])
@login_required
def create_or_update_plan():
    """
    إنشاء أو تحديث خطة تسجيل بالحالة Draft لطالب وفصل معيّن.
    body:
      - student_id (إجباري)
      - semester (إجباري)
      - courses: قائمة أسماء مقررات
    إذا وُجدت خطة Draft/Rejected لنفس الطالب والفصل، يتم الكتابة فوقها.
    """
    data = request.get_json(force=True) or {}
    student_id = (data.get("student_id") or "").strip()
    semester = (data.get("semester") or "").strip()
    courses = data.get("courses") or []

    if not student_id or not semester:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "student_id و semester مطلوبة",
                }
            ),
            400,
        )

    # منع إنشاء/تحديث خطة تسجيل لطالب غير فعّال (سحب ملف، موقوف قيده، خريج)
    with get_connection() as conn:
        cur = conn.cursor()
        cols = [r[1] for r in cur.execute("PRAGMA table_info(students)").fetchall()]
        if "enrollment_status" in cols:
            row = cur.execute(
                "SELECT COALESCE(enrollment_status, 'active') FROM students WHERE student_id = ?",
                (student_id,),
            ).fetchone()
            if row and (row[0] or "active") != "active":
                return (
                    jsonify({
                        "status": "error",
                        "message": "لا يمكن إنشاء أو تعديل خطة تسجيل لطالب غير مسجّل (حالة القيد: سحب ملف أو موقوف قيده أو خريج).",
                    }),
                    400,
                )

    if not isinstance(courses, list):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "قائمة المقررات (courses) يجب أن تكون قائمة",
                }
            ),
            400,
        )

    # الطالب لا يمكنه إنشاء خطة إلا لنفسه
    user_role = session.get("user_role")
    if user_role == "student":
        sid_session = session.get("student_id") or session.get("user")
        student_id = sid_session

    # إزالة التكرار مع الحفاظ على الترتيب
    seen = set()
    dedup = []
    for c in courses:
        if c and c not in seen:
            seen.add(c)
            dedup.append(c)
    courses = dedup

    now = _now_iso()

    with get_connection() as conn:
        cur = conn.cursor()
        # التحقق من حد الوحدات بناءً على المعدل التراكمي قبل الحفظ
        try:
            _enforce_units_limit(cur, student_id, courses)
        except ValueError as ve:
            return jsonify({"status": "error", "message": str(ve), "code": "UNITS_LIMIT"}), 400
        # ابحث عن خطة Draft أو Rejected لنفس الطالب والفصل
        row = cur.execute(
            """
            SELECT id FROM enrollment_plans
            WHERE student_id = ? AND semester = ? AND status IN ('Draft','Rejected')
            ORDER BY id DESC LIMIT 1
            """,
            (student_id, semester),
        ).fetchone()

        if row:
            plan_id = row[0]
            cur.execute(
                """
                UPDATE enrollment_plans
                SET status = 'Draft', rejection_reason = NULL, updated_at = ?
                WHERE id = ?
                """,
                (now, plan_id),
            )
            cur.execute(
                "DELETE FROM enrollment_plan_items WHERE plan_id = ?", (plan_id,)
            )
        else:
            cur.execute(
                """
                INSERT INTO enrollment_plans (student_id, semester, status, rejection_reason, created_at, updated_at)
                VALUES (?,?,?,?,?,?)
                """,
                (student_id, semester, "Draft", None, now, now),
            )
            plan_id = cur.lastrowid

        for cname in courses:
            cur.execute(
                """
                INSERT INTO enrollment_plan_items (plan_id, course_name)
                VALUES (?,?)
                """,
                (plan_id, cname),
            )

        conn.commit()

    try:
        log_activity(
            action="plan_draft_saved",
            details=f"student_id={student_id}, semester={semester}, plan_id={plan_id}, courses={','.join(courses)}",
        )
    except Exception:
        pass

    return jsonify({"status": "ok", "plan_id": plan_id})


@enrollment_bp.route("/plans/<int:plan_id>/submit", methods=["POST"])
@login_required
def submit_plan(plan_id: int):
    """
    تحويل الخطة من Draft إلى Pending.
    لا يتم المساس بجدول registrations هنا.
    """
    now = _now_iso()
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, student_id, semester, status FROM enrollment_plans WHERE id = ?",
            (plan_id,),
        ).fetchone()
        if not row:
            return (
                jsonify({"status": "error", "message": "الخطة غير موجودة"}),
                404,
            )
        status = row[3]
        student_id = row[1]

        # الطالب لا يمكنه إرسال إلا خطته هو
        user_role = session.get("user_role")
        if user_role == "student":
            sid_session = session.get("student_id") or session.get("user")
            if sid_session != student_id:
                return jsonify({"status": "error", "message": "لا يمكنك إرسال خطة طالب آخر"}), 403
        if status not in ("Draft", "Rejected"):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"لا يمكن إرسال خطة حالتها الحالية: {status}",
                    }
                ),
                400,
            )

        # التحقق من حد الوحدات قبل الإرسال
        items = cur.execute(
            "SELECT course_name FROM enrollment_plan_items WHERE plan_id = ?",
            (plan_id,),
        ).fetchall()
        courses = [it[0] for it in items if it and it[0]]
        try:
            _enforce_units_limit(cur, student_id, courses)
        except ValueError as ve:
            return jsonify({"status": "error", "message": str(ve), "code": "UNITS_LIMIT"}), 400
        cur.execute(
            """
            UPDATE enrollment_plans
            SET status = 'Pending', rejection_reason = NULL, updated_at = ?
            WHERE id = ?
            """,
            (now, plan_id),
        )
        conn.commit()

    try:
        log_activity(
            action="plan_submitted",
            details=f"plan_id={plan_id}",
        )
        # إشعار المشرف/الإدارة بوصول خطة جديدة
        target_users = set()
        if SUPERVISOR_USERNAME:
            target_users.add(SUPERVISOR_USERNAME)
        if ADMIN_USERNAME:
            target_users.add(ADMIN_USERNAME)
        for u in target_users:
            create_notification(
                user=u,
                title="خطة تسجيل جديدة معلّقة",
                body=f"خطة جديدة بانتظار المراجعة. رقم الخطة: {plan_id}",
            )
    except Exception:
        pass

    return jsonify({"status": "ok"})


@enrollment_bp.route("/plans/<int:plan_id>/approve", methods=["POST"])
@role_required("admin", "supervisor")
def approve_plan(plan_id: int):
    """
    اعتماد الخطة وتحويلها إلى Approved
    + ترحيل المقررات إلى جدول registrations (يُستبدل تسجيل الطالب بالكامل).
    في هذه المرحلة نعامل المعتمد كـ "مشرف/رئيس قسم" واحد (لاحقاً يمكن فصل الأدوار).
    """
    now = _now_iso()
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, student_id, semester, status FROM enrollment_plans WHERE id = ?",
            (plan_id,),
        ).fetchone()
        if not row:
            return (
                jsonify({"status": "error", "message": "الخطة غير موجودة"}),
                404,
            )
        _, student_id, semester, status = row
        if status not in ("Pending", "Draft"):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"لا يمكن اعتماد خطة حالتها الحالية: {status}",
                    }
                ),
                400,
            )

        # جلب المقررات من الخطة
        items = cur.execute(
            "SELECT course_name FROM enrollment_plan_items WHERE plan_id = ?",
            (plan_id,),
        ).fetchall()
        courses = [it[0] for it in items if it[0]]

        # التحقق من حد الوحدات قبل الاعتماد والترحيل (كحماية إضافية)
        try:
            _enforce_units_limit(cur, student_id, courses)
        except ValueError as ve:
            return jsonify({"status": "error", "message": str(ve), "code": "UNITS_LIMIT"}), 400

        # استبدال تسجيلات الطالب الحالية بهذه المقررات
        cur.execute(
            "DELETE FROM registrations WHERE student_id = ?",
            (student_id,),
        )
        for cname in courses:
            cur.execute(
                "INSERT INTO registrations (student_id, course_name) VALUES (?,?)",
                (student_id, cname),
            )

        # تحديث حالة الخطة
        cur.execute(
            """
            UPDATE enrollment_plans
            SET status = 'Approved', rejection_reason = NULL, updated_at = ?
            WHERE id = ?
            """,
            (now, plan_id),
        )

        conn.commit()

        # إعادة حساب تعارضات الجدول لجميع الطلبة بعد تغيير التسجيلات (ضروري لظهور تعارضات الطلبة مثل حنين)
        conflict_count = 0
        try:
            from backend.services.students import recompute_conflict_report
            conflict_count = recompute_conflict_report(conn)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("فشل إعادة حساب التعارضات بعد اعتماد الخطة: %s", e)

    try:
        log_activity(
            action="plan_approved",
            details=f"plan_id={plan_id}, student_id={student_id}, semester={semester}",
        )
        # إشعار الطالب باعتماد الخطة (نستخدم student_id كمستخدم)
        create_notification(
            user=student_id,
            title="تم اعتماد خطة التسجيل",
            body=f"تم اعتماد خطة التسجيل للفصل {semester}. المقررات: {', '.join(courses) or '—'}",
        )
    except Exception:
        pass

    return jsonify({
        "status": "ok",
        "conflict_count": conflict_count,
        "message": "تم اعتماد الخطة." + (f" تم تحديث تقرير التعارضات ({conflict_count} تعارض)." if conflict_count else " لا توجد تعارضات في الجدول الحالي.")
    })


@enrollment_bp.route("/plans/archive_after_migration", methods=["POST"])
@role_required("admin")
def archive_plans_after_migration():
    """
    أرشفة خطة التسجيل لفصل معيّن بعد ترحيل المقررات إلى كشف الدرجات.

    body JSON:
      - student_id: رقم الطالب
      - semester: وسم الفصل كما هو مخزَّن في جدول enrollment_plans.semester

    تقوم هذه العملية بتحويل حالة الخطة المعتمدة للفصل إلى Archived
    مع عدم لمس جدول registrations أو جدول grades (يتم ذلك في مسار الترحيل نفسه).
    """
    data = request.get_json(force=True) or {}
    student_id = (data.get("student_id") or "").strip()
    semester = (data.get("semester") or "").strip()
    if not student_id or not semester:
        return jsonify({
            "status": "error",
            "message": "student_id و semester مطلوبة",
        }), 400

    now = _now_iso()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE enrollment_plans
            SET status = 'Archived', updated_at = ?
            WHERE student_id = ? AND semester = ? AND status = 'Approved'
            """,
            (now, student_id, semester),
        )
        try:
            # SQLite يوفر دالة changes() للحصول على عدد الصفوف المتأثرة
            count_row = cur.execute("SELECT changes()").fetchone()
            archived_count = int(count_row[0]) if count_row and count_row[0] is not None else 0
        except Exception:
            archived_count = 0
        conn.commit()

    return jsonify({
        "status": "ok",
        "archived": archived_count,
        "message": f"تم أرشفة {archived_count} خطة تسجيل للفصل {semester} للطالب {student_id}",
    })


@enrollment_bp.route("/registration_form_html/<student_id>", methods=["GET"])
@role_required("admin", "supervisor", "student")
def registration_form_html(student_id):
    """
    عرض استمارة التسجيل كصفحة HTML للطباعة من المستعرض (لا يتطلب قالب Word).
    """
    user_role = session.get("user_role")
    if user_role == "supervisor":
        instructor_id = session.get("instructor_id")
        if not instructor_id:
            return jsonify({"status": "error", "message": "لا يوجد ربط بين هذا الحساب وعضو هيئة تدريس", "code": "FORBIDDEN"}), 403
        with get_connection() as conn:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT 1 FROM student_supervisor WHERE student_id = ? AND instructor_id = ? LIMIT 1",
                (student_id, instructor_id),
            ).fetchone()
            if not row:
                return jsonify({"status": "error", "message": "لا يمكنك عرض استمارة لطالب غير مُسند إليك", "code": "FORBIDDEN"}), 403

    semester_param = (request.args.get("semester") or "").strip()
    source = (request.args.get("source") or "plan").strip().lower()
    try:
        ctx = _build_registration_form_context(student_id, semester_param, source=source)
    except Exception as e:
        current_app.logger.exception("registration_form_html context failed for %s", student_id)
        return (
            render_template(
                "registration_form_error.html",
                error_message=str(e) or "خطأ غير معروف",
            ),
            500,
        )
    return render_template("registration_form_print.html", **ctx)


@enrollment_bp.route("/print_registration_form/<student_id>", methods=["GET"])
@role_required("admin", "supervisor", "student")
def print_registration_form(student_id):
    """
    توليد ملف Word لاستمارة تسجيل مقررات دراسية لطالب محدد.
    يقبل اختيارياً ?semester= لتحديد فصل معيّن.
    """
    # تقييد المشرف: لا يطبع إلا لطلبته المسندين إليه
    user_role = session.get("user_role")
    if user_role == "supervisor":
        instructor_id = session.get("instructor_id")
        if not instructor_id:
            return jsonify({"status": "error", "message": "لا يوجد ربط بين هذا الحساب وعضو هيئة تدريس", "code": "FORBIDDEN"}), 403
        with get_connection() as conn:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT 1 FROM student_supervisor WHERE student_id = ? AND instructor_id = ? LIMIT 1",
                (student_id, instructor_id),
            ).fetchone()
            if not row:
                return jsonify({"status": "error", "message": "لا يمكنك طباعة استمارة لطالب غير مُسند إليك", "code": "FORBIDDEN"}), 403

    if not _ensure_docxtpl():
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "مكتبة docxtpl غير متوفرة. تمت محاولة التثبيت تلقائياً ولم تنجح. نفّذ يدوياً: pip install docxtpl ثم أعد تشغيل الخادم.",
                }
            ),
            500,
        )

    semester_param = (request.args.get("semester") or "").strip()
    source = (request.args.get("source") or "plan").strip().lower()
    ctx = _build_registration_form_context(student_id, semester_param, source=source)

    template_path = os.path.join(
        current_app.root_path, "frontend", "templates", "registration_form_template.docx"
    )
    if not os.path.exists(template_path):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "قالب استمارة التسجيل غير موجود على الخادم.",
                }
            ),
            500,
        )

    doc = DocxTemplate(template_path)
    doc.render(ctx)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
    try:
        doc.save(tmp.name)
        tmp.close()
        filename = f"registration_{ctx['student_id']}_{ctx['semester'] or 'semester'}.docx"
        return send_file(
            tmp.name,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    finally:
        # يمكن لاحقاً إضافة آلية لتنظيف الملفات المؤقتة القديمة
        pass


@enrollment_bp.route("/plans/<int:plan_id>/reject", methods=["POST"])
@role_required("admin", "supervisor")
def reject_plan(plan_id: int):
    """
    رفض الخطة مع حفظ سبب الرفض.
    body:
      - reason: نص اختياري لكن مستحسن
    """
    data = (request.get_json(force=True) or {})
    reason = (data.get("reason") or "").strip()
    now = _now_iso()

    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, student_id, semester, status FROM enrollment_plans WHERE id = ?",
            (plan_id,),
        ).fetchone()
        if not row:
            return (
                jsonify({"status": "error", "message": "الخطة غير موجودة"}),
                404,
            )
        _, student_id, semester, status = row
        if status not in ("Pending", "Draft"):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"لا يمكن رفض خطة حالتها الحالية: {status}",
                    }
                ),
                400,
            )

        cur.execute(
            """
            UPDATE enrollment_plans
            SET status = 'Rejected', rejection_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (reason or None, now, plan_id),
        )
        conn.commit()

    try:
        log_activity(
            action="plan_rejected",
            details=f"plan_id={plan_id}, student_id={student_id}, semester={semester}, reason={reason}",
        )
        # إشعار الطالب برفض الخطة مع السبب
        create_notification(
            user=student_id,
            title="تم رفض خطة التسجيل",
            body=f"تم رفض خطة التسجيل للفصل {semester}. السبب: {reason or 'لم يتم تحديد سبب.'}",
        )
    except Exception:
        pass

    return jsonify({"status": "ok"})

