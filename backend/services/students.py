import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models.models import Student
from flask import Blueprint, request, jsonify, render_template, current_app, send_file, session
from backend.core.auth import login_required, role_required
from collections import defaultdict
import sqlite3, pandas as pd, io, datetime, hashlib
from .utilities import (
    get_connection,
    table_to_dicts,
    DB_FILE,
    df_from_query,
    excel_response_from_df,
    excel_response_from_frames,
    pdf_response_from_html,
    log_activity,
    get_schedule_published_at,
    get_current_term,
)
from .prereg_helpers import evaluate_courses_prereqs
from .attendance_export_core import (
    build_schedule_semester_match,
    collect_attendance_export_state as _collect_attendance_export_state,
    course_rows_with_meta,
    fallback_distinct_attendance_courses,
)
from backend.database.database import is_postgresql

students_bp = Blueprint("students", __name__)


def _ensure_registration_signature_tables(cur):
    # على PostgreSQL الجداول تُنشأ عبر Alembic (DDL متوافق)؛ إنشاء SQLite هنا يفشل (AUTOINCREMENT إلخ).
    if is_postgresql():
        return
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS registration_signatures (
            student_id TEXT NOT NULL,
            term TEXT NOT NULL,
            student_signed INTEGER NOT NULL DEFAULT 0,
            signed_at TEXT,
            signature_note TEXT,
            form_file_id INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            PRIMARY KEY (student_id, term)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS registration_form_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            term TEXT NOT NULL,
            original_name TEXT DEFAULT '',
            stored_path TEXT NOT NULL,
            mime_type TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            sha256 TEXT DEFAULT '',
            uploaded_by TEXT DEFAULT '',
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS registration_signature_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            term TEXT NOT NULL,
            form_version_id INTEGER,
            form_version_no INTEGER DEFAULT 0,
            student_signed INTEGER NOT NULL DEFAULT 0,
            signed_at TEXT,
            signature_note TEXT,
            form_file_id INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            UNIQUE(student_id, term, form_version_id)
        )
        """
    )


def _is_instructor_or_supervisor_view_only() -> bool:
    role = (session.get("user_role") or "").strip()
    return role in ("instructor", "supervisor")


def _enrollment_label_ar(enrollment_status: str) -> str:
    es = str(enrollment_status or "active").strip().lower()
    return {
        "active": "مسجّل",
        "withdrawn": "سحب ملف",
        "suspended": "إيقاف قيد",
        "graduated": "خريج",
    }.get(es, enrollment_status or "—")


def _format_status_action_period(term: str, year: str) -> str:
    t = (term or "").strip()
    y = (year or "").strip()
    if t and y:
        return f"{t} — {y}"
    return t or y


def students_filtered_from_request(request):
    """
    قائمة طلاب (dicts) حسب:
      active_only=1 → مسجّلون فقط
      enrollment_status=active|withdrawn|suspended|graduated → يُفضّل على active_only
      join_term / join_year
    """
    from backend.core.services import StudentService

    active_only = request.args.get("active_only", "").lower() in ("1", "true", "yes")
    enrollment_status = (request.args.get("enrollment_status") or "").strip().lower()
    join_term = (request.args.get("join_term") or "").strip()
    join_year = (request.args.get("join_year") or "").strip()
    allowed_es = {"active", "withdrawn", "suspended", "graduated"}
    if enrollment_status in allowed_es:
        students = StudentService.get_all_students(active_only=False)
        students = [s for s in students if (s.get("enrollment_status") or "active") == enrollment_status]
    elif active_only:
        students = StudentService.get_all_students(active_only=True)
    else:
        students = StudentService.get_all_students(active_only=False)
        # السلوك الافتراضي: إخفاء "سحب ملف" من قوائم الطلبة التشغيلية
        students = [s for s in students if (s.get("enrollment_status") or "active") != "withdrawn"]
    if join_term:
        students = [s for s in students if (s.get("join_term") or "").strip() == join_term]
    if join_year:
        students = [s for s in students if (s.get("join_year") or "").strip() == join_year]
    return students


def students_filter_summary_ar(request) -> str:
    active_only = request.args.get("active_only", "").lower() in ("1", "true", "yes")
    enrollment_status = (request.args.get("enrollment_status") or "").strip().lower()
    join_term = (request.args.get("join_term") or "").strip()
    join_year = (request.args.get("join_year") or "").strip()
    parts = []
    allowed_es = {"active", "withdrawn", "suspended", "graduated"}
    if enrollment_status in allowed_es:
        parts.append("حالة القيد: " + _enrollment_label_ar(enrollment_status))
    elif active_only:
        parts.append("نطاق: مسجّلون فقط")
    else:
        parts.append("نطاق: جميع حالات القيد (مع إخفاء سحب الملف)")
    if join_term:
        parts.append("فصل الالتحاق: " + join_term)
    if join_year:
        parts.append("سنة الالتحاق: " + join_year)
    return " — ".join(parts) if parts else "بدون فلترة"


# -----------------------------
# شرط المقررات الاختيارية بعد 100 وحدة
# -----------------------------
@students_bp.route("/electives_status")
@role_required("admin", "supervisor")
def electives_status_api():
    sid = normalize_sid(request.args.get("student_id"))
    if not sid:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        # Scope: تقييد الوصول حسب الدور (منع تسريب عند وصول instructor عبر normalize)
        allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed_student_ids is not None and sid not in allowed_student_ids:
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        try:
            from backend.services.electives import check_electives_requirement
            data = check_electives_requirement(cur, sid, required_electives=3)
        except Exception:
            data = {"active": False, "ok": True, "waived": False}
    return jsonify({"status": "ok", "data": data})


@students_bp.route("/electives_report")
@role_required("admin", "supervisor")
def electives_report_api():
    """
    تقرير: الطلبة الذين تجاوزوا 100 وحدة ولا يزالون أقل من 3 مقررات اختيارية (بدون استثناء).
    """
    items = []
    with get_connection() as conn:
        cur = conn.cursor()
        # Scope: تقييد قائمة الطلاب حسب الدور
        allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed_student_ids is not None and not allowed_student_ids:
            return jsonify({"status": "ok", "items": []})
        try:
            from backend.services.electives import check_electives_requirement
        except Exception:
            check_electives_requirement = None
        if allowed_student_ids is None:
            rows = cur.execute(
                "SELECT student_id, COALESCE(student_name,'') FROM students ORDER BY student_name, student_id"
            ).fetchall()
        else:
            placeholders = ",".join("?" for _ in allowed_student_ids)
            rows = cur.execute(
                f"SELECT student_id, COALESCE(student_name,'') FROM students WHERE student_id IN ({placeholders}) "
                "ORDER BY student_name, student_id",
                list(allowed_student_ids),
            ).fetchall()
        for r in rows:
            sid = r[0] if isinstance(r, (list, tuple)) else r["student_id"]
            name = r[1] if isinstance(r, (list, tuple)) else (r["COALESCE(student_name,'')"] if "COALESCE(student_name,'')" in r.keys() else r.get("student_name",""))
            if not check_electives_requirement:
                continue
            st = check_electives_requirement(cur, sid, required_electives=3)
            if st.get("active") and (not st.get("ok")) and (not st.get("waived")):
                items.append({
                    "student_id": sid,
                    "student_name": name or "",
                    **st,
                })
    return jsonify({"status": "ok", "items": items})


@students_bp.route("/electives_report/excel")
@role_required("admin", "supervisor")
def electives_report_excel():
    r = electives_report_api()
    # electives_report_api returns (json, status) sometimes; normalize
    payload = r[0].get_json() if isinstance(r, tuple) else r.get_json()
    items = payload.get("items", []) if payload else []
    df = pd.DataFrame(items or [])
    if not df.empty:
        # ترتيب أعمدة ودية
        cols = ["student_id", "student_name", "completed_units", "electives_completed", "required_electives"]
        keep = [c for c in cols if c in df.columns] + [c for c in df.columns if c not in cols]
        df = df[keep]
    return excel_response_from_df(df, filename_prefix="electives_report")


@students_bp.route("/electives_report/pdf")
@role_required("admin", "supervisor")
def electives_report_pdf():
    r = electives_report_api()
    payload = r[0].get_json() if isinstance(r, tuple) else r.get_json()
    items = payload.get("items", []) if payload else []
    rows_html = ""
    for it in items:
        rows_html += (
            "<tr>"
            f"<td>{it.get('student_id','')}</td>"
            f"<td>{it.get('student_name','')}</td>"
            f"<td style='text-align:center'>{it.get('completed_units','')}</td>"
            f"<td style='text-align:center'>{it.get('electives_completed','')}</td>"
            f"<td style='text-align:center'>{it.get('required_electives','')}</td>"
            "</tr>"
        )
    html = f"""
    <html dir="rtl" lang="ar">
    <head>
      <meta charset="utf-8"/>
      <style>
        body {{ font-family: Arial, sans-serif; }}
        h2 {{ margin: 0 0 10px 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ border: 1px solid #999; padding: 6px; font-size: 12px; }}
        th {{ background: #f2f2f2; }}
      </style>
    </head>
    <body>
      <h2>تقرير المقررات الاختيارية (بعد 100 وحدة)</h2>
      <p>يعرض الطلبة الذين تجاوزوا 100 وحدة ولم يكملوا 3 مقررات اختيارية (بدون استثناء).</p>
      <table>
        <thead>
          <tr>
            <th>رقم الطالب</th>
            <th>الاسم</th>
            <th>الوحدات المكتملة</th>
            <th>الاختيارية المكتملة</th>
            <th>المطلوب</th>
          </tr>
        </thead>
        <tbody>
          {rows_html or "<tr><td colspan='5' style='text-align:center'>لا توجد بيانات</td></tr>"}
        </tbody>
      </table>
    </body>
    </html>
    """
    return pdf_response_from_html(html, filename_prefix="electives_report")


# -----------------------------
# تقرير: أعداد الطلبة حسب المقرر (التسجيلات الفعلية في registrations)
# -----------------------------
def _course_registration_count_rows(conn):
    """صف واحد لكل مقرر: عدد الطلبة المسجّلين فعلياً في جدول التسجيلات."""
    cur = conn.cursor()
    cols_stu = [r[1] for r in cur.execute("PRAGMA table_info(students)").fetchall()]
    active_only = "enrollment_status" in cols_stu
    if active_only:
        q = """
        SELECT r.course_name,
               COALESCE(c.course_code, '') AS course_code,
               COALESCE(c.units, 0) AS units,
               COUNT(DISTINCT r.student_id) AS student_count
        FROM registrations r
        LEFT JOIN courses c ON c.course_name = r.course_name
        LEFT JOIN students s ON s.student_id = r.student_id
        WHERE COALESCE(s.enrollment_status, 'active') = 'active'
        GROUP BY r.course_name, c.course_code, c.units
        ORDER BY r.course_name
        """
    else:
        q = """
        SELECT r.course_name,
               COALESCE(c.course_code, '') AS course_code,
               COALESCE(c.units, 0) AS units,
               COUNT(DISTINCT r.student_id) AS student_count
        FROM registrations r
        LEFT JOIN courses c ON c.course_name = r.course_name
        GROUP BY r.course_name, c.course_code, c.units
        ORDER BY r.course_name
        """
    rows = cur.execute(q).fetchall()
    items = []
    for row in rows or []:
        d = dict(row)
        items.append({
            "course_name": (d.get("course_name") or "").strip(),
            "course_code": (d.get("course_code") or "").strip(),
            "units": int(d.get("units") or 0),
            "student_count": int(d.get("student_count") or 0),
        })
    return items


@students_bp.route("/course_registration_counts")
@role_required("admin", "admin_main", "head_of_department")
def course_registration_counts_api():
    """تقرير مجمّع: عدد الطلبة لكل مقرر من التسجيلات الفعلية."""
    with get_connection() as conn:
        items = _course_registration_count_rows(conn)
    total_registrations = sum(i["student_count"] for i in items)
    # طلبة مميّزون وقعوا في تسجيل واحد على الأقل (ضمن نفس نطاق التقرير)
    distinct_students = 0
    with get_connection() as conn:
        cur = conn.cursor()
        cols_stu = [r[1] for r in cur.execute("PRAGMA table_info(students)").fetchall()]
        active_only = "enrollment_status" in cols_stu
        if active_only:
            row = cur.execute(
                """
                SELECT COUNT(DISTINCT r.student_id)
                FROM registrations r
                LEFT JOIN students s ON s.student_id = r.student_id
                WHERE COALESCE(s.enrollment_status, 'active') = 'active'
                """
            ).fetchone()
        else:
            row = cur.execute("SELECT COUNT(DISTINCT student_id) FROM registrations").fetchone()
        if row:
            distinct_students = int(row[0] or 0)
    return jsonify({
        "status": "ok",
        "items": items,
        "summary": {
            "courses_with_registrations": len(items),
            "total_registration_slots": total_registrations,
            "distinct_students_with_registration": distinct_students,
        },
    })


@students_bp.route("/course_registration_counts/excel")
@role_required("admin", "admin_main", "head_of_department")
def course_registration_counts_excel():
    with get_connection() as conn:
        items = _course_registration_count_rows(conn)
    df = pd.DataFrame(items or [])
    if not df.empty:
        df = df.rename(columns={
            "course_name": "اسم المقرر",
            "course_code": "رمز المقرر",
            "units": "الوحدات",
            "student_count": "عدد الطلبة المسجلين",
        })
    return excel_response_from_df(df, filename_prefix="course_registration_counts")


@students_bp.route("/course_registration_counts/pdf")
@role_required("admin", "admin_main", "head_of_department")
def course_registration_counts_pdf():
    with get_connection() as conn:
        items = _course_registration_count_rows(conn)
    rows_html = ""
    for it in items:
        rows_html += (
            "<tr>"
            f"<td>{it.get('course_name','')}</td>"
            f"<td style='text-align:center'>{it.get('course_code','')}</td>"
            f"<td style='text-align:center'>{it.get('units') if it.get('units') is not None else ''}</td>"
            f"<td style='text-align:center'>{it.get('student_count','')}</td>"
            "</tr>"
        )
    n = len(items)
    tot = sum(it.get("student_count") or 0 for it in items)
    html = f"""
    <html dir="rtl" lang="ar">
    <head>
      <meta charset="utf-8"/>
      <style>
        body {{ font-family: Arial, sans-serif; }}
        h2 {{ margin: 0 0 10px 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ border: 1px solid #999; padding: 6px; font-size: 12px; }}
        th {{ background: #f2f2f2; }}
      </style>
    </head>
    <body>
      <h2>تقرير أعداد التسجيل الفعلي بالمقررات</h2>
      <p>يُحتسب من جدول التسجيلات الفعلية؛ يُفضّل احتساب الطلبة ذوي القيد النشط عند توفر حالة القيد.</p>
      <p><strong>عدد المقررات:</strong> {n} — <strong>مجموع التسجيلات (مقعد-طالب):</strong> {tot}</p>
      <table>
        <thead>
          <tr>
            <th>المقرر</th>
            <th>رمز المقرر</th>
            <th>الوحدات</th>
            <th>عدد الطلبة</th>
          </tr>
        </thead>
        <tbody>
          {rows_html or "<tr><td colspan='4' style='text-align:center'>لا توجد تسجيلات</td></tr>"}
        </tbody>
      </table>
    </body>
    </html>
    """
    return pdf_response_from_html(html, filename_prefix="course_registration_counts")


# -----------------------------
# تقرير سجل الإضافة والإسقاط (المواد المضافة والمسقطة + التواريخ)
# -----------------------------
def _registration_changes_report_items(
    conn,
    date_from=None,
    date_to=None,
    student_id=None,
    student_ids=None,
    action=None,
    course_name_like=None,
):
    """استعلام registration_changes_log مع فلترة اختيارية. يرجع قائمة قامات."""
    cur = conn.cursor()
    sql = """
        SELECT id, student_id, student_name, term, course_name, course_code, units,
               action, action_phase, action_time, performed_by, reason, notes
        FROM registration_changes_log
        WHERE 1=1
    """
    params = []
    if date_from:
        sql += " AND date(action_time) >= date(?)"
        params.append(date_from)
    if date_to:
        sql += " AND date(action_time) <= date(?)"
        params.append(date_to)
    if student_id:
        sql += " AND student_id = ?"
        params.append(student_id.strip())
    elif student_ids:
        # فلترة حسب مجموعة طلاب (يُستخدم لتقييد الوصول حسب الدور)
        ids = [normalize_sid(sid) for sid in (student_ids or []) if normalize_sid(sid)]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            sql += f" AND student_id IN ({placeholders})"
            params.extend(ids)
    if action and str(action).lower() in ("add", "drop", "change"):
        sql += " AND action = ?"
        params.append(str(action).lower())
    if course_name_like and course_name_like.strip():
        sql += " AND (course_name LIKE ? OR course_code LIKE ?)"
        q = "%" + course_name_like.strip() + "%"
        params.extend([q, q])
    sql += " ORDER BY action_time DESC, id DESC"
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    items = []
    for row in rows:
        items.append(dict(zip(cols, row)))
    return items


@students_bp.route("/registration_changes_report")
@role_required("admin", "supervisor")
def registration_changes_report_api():
    """
    تقرير: المواد المضافة والمسقطة مع تواريخ الإضافة والإسقاط من registration_changes_log.
    معاملات اختيارية: date_from, date_to, student_id, action (add/drop), course_name (بحث جزئي).
    """
    date_from = request.args.get("date_from", "").strip() or None
    date_to = request.args.get("date_to", "").strip() or None
    student_id = request.args.get("student_id", "").strip() or None
    action = request.args.get("action", "").strip() or None
    course_name = request.args.get("course_name", "").strip() or None
    with get_connection() as conn:
        # Scope: تقييد الوصول حسب الدور
        allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed_student_ids is not None:
            if not allowed_student_ids:
                return jsonify({"status": "ok", "items": []})

            student_id_norm = normalize_sid(student_id) if student_id else ""
            if student_id_norm:
                if student_id_norm not in allowed_student_ids:
                    return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
                # نستخدم student_id كما هو
                student_ids = None
            else:
                student_ids = allowed_student_ids
            student_id = student_id_norm if student_id_norm else None
        else:
            student_ids = None

        items = _registration_changes_report_items(
            conn, date_from=date_from, date_to=date_to,
            student_id=student_id, student_ids=student_ids,
            action=action, course_name_like=course_name
        )
    return jsonify({"status": "ok", "items": items})


@students_bp.route("/registration_changes_report/excel")
@role_required("admin", "supervisor")
def registration_changes_report_excel():
    """تصدير تقرير الإضافة والإسقاط إلى Excel مع نفس الفلاتر."""
    date_from = request.args.get("date_from", "").strip() or None
    date_to = request.args.get("date_to", "").strip() or None
    student_id = request.args.get("student_id", "").strip() or None
    action = request.args.get("action", "").strip() or None
    course_name = request.args.get("course_name", "").strip() or None
    with get_connection() as conn:
        # Scope: تقييد الوصول حسب الدور
        allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed_student_ids is not None:
            if not allowed_student_ids:
                df = pd.DataFrame(columns=[])
                return excel_response_from_df(df, filename_prefix="registration_changes_report")

            student_id_norm = normalize_sid(student_id) if student_id else ""
            if student_id_norm:
                if student_id_norm not in allowed_student_ids:
                    return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
                student_ids = None
            else:
                student_ids = allowed_student_ids
            student_id = student_id_norm if student_id_norm else None
        else:
            student_ids = None

        items = _registration_changes_report_items(
            conn, date_from=date_from, date_to=date_to,
            student_id=student_id, student_ids=student_ids,
            action=action, course_name_like=course_name
        )
    df = pd.DataFrame(items or [])
    if not df.empty and "action_time" in df.columns:
        df = df.sort_values("action_time", ascending=False)
    return excel_response_from_df(df, filename_prefix="registration_changes_report")


@students_bp.route("/registration_changes_report/pdf")
@role_required("admin", "supervisor")
def registration_changes_report_pdf():
    """تصدير تقرير الإضافة والإسقاط إلى PDF بنفس أعمدة التقرير ومع نفس الفلاتر."""
    date_from = request.args.get("date_from", "").strip() or None
    date_to = request.args.get("date_to", "").strip() or None
    student_id = request.args.get("student_id", "").strip() or None
    action = request.args.get("action", "").strip() or None
    course_name = request.args.get("course_name", "").strip() or None
    with get_connection() as conn:
        # Scope: تقييد الوصول حسب الدور
        allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed_student_ids is not None:
            if not allowed_student_ids:
                return pdf_response_from_html(
                    """
                    <html dir="rtl" lang="ar"><body><p style="font-family:Arial,sans-serif;">لا توجد بيانات</p></body></html>
                    """,
                    filename_prefix="registration_changes_report",
                )

            student_id_norm = normalize_sid(student_id) if student_id else ""
            if student_id_norm:
                if student_id_norm not in allowed_student_ids:
                    return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
                student_ids = None
            else:
                student_ids = allowed_student_ids
            student_id = student_id_norm if student_id_norm else None
        else:
            student_ids = None

        items = _registration_changes_report_items(
            conn, date_from=date_from, date_to=date_to,
            student_id=student_id, student_ids=student_ids,
            action=action, course_name_like=course_name
        )
    action_labels = {"add": "إضافة", "drop": "إسقاط", "change": "تعديل"}
    rows_html = ""
    for it in items:
        al = action_labels.get(it.get("action"), it.get("action") or "")
        rows_html += (
            "<tr>"
            f"<td>{_h(it.get('action_time'))}</td>"
            f"<td>{_h(it.get('student_id'))}</td>"
            f"<td>{_h(it.get('student_name'))}</td>"
            f"<td>{_h(it.get('term'))}</td>"
            f"<td>{_h(it.get('course_name'))}</td>"
            f"<td>{_h(it.get('course_code'))}</td>"
            f"<td style='text-align:center'>{_h(it.get('units'))}</td>"
            f"<td>{_h(al)}</td>"
            f"<td>{_h(it.get('performed_by'))}</td>"
            f"<td>{_h(it.get('reason') or it.get('notes'))}</td>"
            "</tr>"
        )

    html = f"""
    <html dir="rtl" lang="ar">
    <head>
      <meta charset="utf-8"/>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 12px; }}
        h2 {{ margin: 0 0 10px 0; }}
        p {{ margin: 0 0 8px 0; color: #444; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
        th, td {{ border: 1px solid #999; padding: 5px; }}
        th {{ background: #f2f2f2; }}
      </style>
    </head>
    <body>
      <h2>تقرير الإضافة والإسقاط</h2>
      <p>سجل المواد المضافة والمسقطة مع تواريخ الإضافة والإسقاط ومنفّذ العملية.</p>
      <table>
        <thead>
          <tr>
            <th>التاريخ والوقت</th>
            <th>رقم الطالب</th>
            <th>اسم الطالب</th>
            <th>الفصل</th>
            <th>المقرر</th>
            <th>الرمز</th>
            <th>الوحدات</th>
            <th>العملية</th>
            <th>منفّذ بواسطة</th>
            <th>سبب / ملاحظات</th>
          </tr>
        </thead>
        <tbody>
          {rows_html or "<tr><td colspan='10' style='text-align:center'>لا توجد بيانات</td></tr>"}
        </tbody>
      </table>
    </body>
    </html>
    """
    return pdf_response_from_html(html, filename_prefix="registration_changes_report")


def _h(v):
    """هروب بسيط للنص في HTML."""
    if v is None:
        return ""
    s = str(v).strip()
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# -----------------------------
# تقارير: المقررات غير المنجزة + المقررات الراسب فيها الطلبة
# (تعريف النجاح: >= 50 أو نص "ناجح")
# -----------------------------
PASSING_GRADE = 50


def _grade_to_float_or_none(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except Exception:
            return None
    if isinstance(v, str):
        t = v.strip()
        if not t:
            return None
        # normalize Arabic digits? keep simple
        t2 = t.replace(",", ".")
        try:
            return float(t2)
        except Exception:
            return None
    return None


def _grade_pass_status(v):
    """
    يرجع:
      - True/False إذا أمكن تحديد نجاح/رسوب
      - None إذا لا يمكن تحديدها
    يدعم:
      - رقمية (>=50)
      - نصية "ناجح" / "راسب"
    """
    if v is None:
        return None
    if isinstance(v, str):
        t = v.strip()
        if not t:
            return None
        if "ناجح" in t:
            return True
        if "راسب" in t:
            return False
        # fallback numeric parse
        f = _grade_to_float_or_none(t)
        return (f >= PASSING_GRADE) if f is not None else None
    f = _grade_to_float_or_none(v)
    return (f >= PASSING_GRADE) if f is not None else None


def _best_grade_key(v):
    """
    مفتاح مقارنة لأفضل درجة:
    - رقمية: قيمتها
    - نصية: ناجح=100، راسب=0
    - غير معروف: -1
    """
    if v is None:
        return -1.0
    f = _grade_to_float_or_none(v)
    if f is not None:
        return f
    st = _grade_pass_status(v)
    if st is True:
        return 100.0
    if st is False:
        return 0.0
    return -1.0


def _best_grades_map(conn, student_id=None, student_ids=None, course_name_like=None):
    """
    يجمع كل محاولات grades ويحسب أفضل درجة لكل (طالب, مقرر).
    يرجع قاموس: (sid, course_name) -> info
    """
    cur = conn.cursor()
    sql = """
        SELECT g.student_id,
               COALESCE(s.student_name,'') AS student_name,
               g.course_name,
               COALESCE(g.course_code,'') AS course_code,
               COALESCE(g.units,0) AS units,
               COALESCE(g.semester,'') AS semester,
               g.grade
        FROM grades g
        LEFT JOIN students s ON s.student_id = g.student_id
        WHERE 1=1
    """
    params = []
    if student_id:
        sql += " AND g.student_id = ?"
        params.append(str(student_id).strip())
    elif student_ids:
        ids = [normalize_sid(sid) for sid in (student_ids or []) if normalize_sid(sid)]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            sql += f" AND g.student_id IN ({placeholders})"
            params.extend(ids)
        else:
            return {}
    if course_name_like and str(course_name_like).strip():
        q = "%" + str(course_name_like).strip() + "%"
        sql += " AND (g.course_name LIKE ? OR g.course_code LIKE ?)"
        params.extend([q, q])
    sql += " ORDER BY g.student_id, g.course_name"
    rows = cur.execute(sql, params).fetchall()

    best = {}
    for r in rows:
        sid = str(r[0] if isinstance(r, (list, tuple)) else r["student_id"]).strip()
        sname = r[1] if isinstance(r, (list, tuple)) else r["student_name"]
        cname = r[2] if isinstance(r, (list, tuple)) else r["course_name"]
        ccode = r[3] if isinstance(r, (list, tuple)) else r["course_code"]
        units = r[4] if isinstance(r, (list, tuple)) else r["units"]
        sem = r[5] if isinstance(r, (list, tuple)) else r["semester"]
        grade = r[6] if isinstance(r, (list, tuple)) else r["grade"]
        if not cname:
            continue

        k = (sid, cname)
        entry = best.get(k)
        if not entry:
            entry = {
                "student_id": sid,
                "student_name": sname or "",
                "course_name": cname,
                "course_code": ccode or "",
                "units": int(units or 0),
                "attempts": 0,
                "best_grade": grade,
                "best_grade_key": _best_grade_key(grade),
                "best_semester": sem or "",
            }
            best[k] = entry
        entry["attempts"] += 1
        # prefer non-zero units if available
        if (entry.get("units") or 0) <= 0 and (units or 0) > 0:
            entry["units"] = int(units or 0)
        # best grade by key
        gk = _best_grade_key(grade)
        if gk > (entry.get("best_grade_key") or -1):
            entry["best_grade"] = grade
            entry["best_grade_key"] = gk
            entry["best_semester"] = sem or ""
    # determine pass/fail
    for entry in best.values():
        st = _grade_pass_status(entry.get("best_grade"))
        # if unknown but numeric key exists, deduce
        if st is None:
            fk = entry.get("best_grade_key")
            if fk is not None and fk >= 0:
                st = fk >= PASSING_GRADE
        entry["passed"] = bool(st) if st is not None else False
        # best_grade_display
        bg = entry.get("best_grade")
        if bg is None:
            entry["best_grade_display"] = "—"
        else:
            entry["best_grade_display"] = str(bg)
    return best


def _students_scope_rows(conn, student_id=None, student_ids=None):
    """يرجع قائمة طلاب ضمن النطاق المطلوب."""
    cur = conn.cursor()
    if student_id:
        sid = normalize_sid(student_id)
        rows = cur.execute(
            "SELECT student_id, COALESCE(student_name,'') AS student_name FROM students WHERE student_id = ?",
            (sid,),
        ).fetchall()
    elif student_ids is not None:
        ids = [normalize_sid(s) for s in (student_ids or []) if normalize_sid(s)]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = cur.execute(
            f"SELECT student_id, COALESCE(student_name,'') AS student_name FROM students WHERE student_id IN ({placeholders})",
            ids,
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT student_id, COALESCE(student_name,'') AS student_name FROM students"
        ).fetchall()
    return [{"student_id": normalize_sid(r[0]), "student_name": (r[1] or "")} for r in (rows or [])]


def _courses_catalog_rows(conn, course_name_like=None):
    cur = conn.cursor()
    sql = """
        SELECT COALESCE(course_name,'') AS course_name,
               COALESCE(course_code,'') AS course_code,
               COALESCE(units,0) AS units
        FROM courses
        WHERE COALESCE(course_name,'') <> ''
    """
    params = []
    if course_name_like and str(course_name_like).strip():
        q = "%" + str(course_name_like).strip() + "%"
        sql += " AND (course_name LIKE ? OR course_code LIKE ?)"
        params.extend([q, q])
    sql += " ORDER BY course_name"
    rows = cur.execute(sql, params).fetchall()
    out = []
    seen = set()
    for r in rows or []:
        cname = (r[0] or "").strip()
        ccode = (r[1] or "").strip()
        units = int(r[2] or 0)
        if not cname:
            continue
        # dedupe: prefer course_code when exists, otherwise normalized name
        key = ("code", ccode.lower()) if ccode else ("name", _normalize_course_name_key(cname))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "course_name": cname,
            "course_code": ccode,
            "units": units,
        })
    return out


def _normalize_course_name_key(name: str) -> str:
    """تطبيع بسيط لاسم المقرر لتقليل مشاكل المطابقة النصية."""
    s = str(name or "").strip().lower()
    # توحيد مسافات/شرطات شائعة
    s = s.replace("ـ", "")
    for ch in ("-", "_", "/", "\\"):
        s = s.replace(ch, " ")
    s = " ".join(s.split())
    return s


def _classified_uncompleted_items(conn, student_id=None, student_ids=None, course_name_like=None, reason_filter=None):
    """
    التصنيف الموحّد:
      - not_registered: المقرر موجود بالخطة (courses) ولا توجد له أي محاولة في grades
      - failed: توجد محاولة/محاولات لكن أفضل نتيجة < 50 أو "راسب"
    """
    students = _students_scope_rows(conn, student_id=student_id, student_ids=student_ids)
    if not students:
        return []
    catalog = _courses_catalog_rows(conn, course_name_like=course_name_like)
    if not catalog:
        return []

    scope_ids = [s["student_id"] for s in students]
    best = _best_grades_map(conn, student_ids=scope_ids, course_name_like=course_name_like)
    sname_map = {s["student_id"]: s.get("student_name") or "" for s in students}
    # فهارس مطابقة لكل طالب:
    # 1) by code (أدق)
    # 2) by normalized course name (fallback)
    by_student_code = {}
    by_student_name_norm = {}
    for (_sid, _cname), entry in (best or {}).items():
        sid = normalize_sid(_sid)
        code = str(entry.get("course_code") or "").strip().lower()
        cname_norm = _normalize_course_name_key(entry.get("course_name") or "")
        if sid not in by_student_code:
            by_student_code[sid] = {}
        if sid not in by_student_name_norm:
            by_student_name_norm[sid] = {}
        # إذا تكرر نفس الكود/الاسم نحتفظ بالأفضل
        if code:
            old = by_student_code[sid].get(code)
            if (not old) or ((entry.get("best_grade_key") or -1) > (old.get("best_grade_key") or -1)):
                by_student_code[sid][code] = entry
        if cname_norm:
            old = by_student_name_norm[sid].get(cname_norm)
            if (not old) or ((entry.get("best_grade_key") or -1) > (old.get("best_grade_key") or -1)):
                by_student_name_norm[sid][cname_norm] = entry

    out = []
    out_seen = set()
    for sid in scope_ids:
        for c in catalog:
            cname = c["course_name"]
            ccode_norm = str(c.get("course_code") or "").strip().lower()
            cname_norm = _normalize_course_name_key(cname)
            # المطابقة: code أولاً ثم اسم مُطبع
            b = None
            if ccode_norm:
                b = (by_student_code.get(sid) or {}).get(ccode_norm)
            if not b and cname_norm:
                b = (by_student_name_norm.get(sid) or {}).get(cname_norm)
            if b and b.get("passed"):
                continue

            if b:
                reason = "failed"
                reason_label = "راسب"
                attempts = int(b.get("attempts") or 0)
                best_grade_display = b.get("best_grade_display") or "—"
                best_semester = b.get("best_semester") or ""
                units = int(b.get("units") or c.get("units") or 0)
                course_code = (b.get("course_code") or c.get("course_code") or "").strip()
            else:
                reason = "not_registered"
                reason_label = "غير مسجل"
                attempts = 0
                best_grade_display = "—"
                best_semester = ""
                units = int(c.get("units") or 0)
                course_code = (c.get("course_code") or "").strip()

            if reason_filter and reason != reason_filter:
                continue

            # dedupe final rows per student+course
            dedupe_key = (sid, ("code", course_code.lower()) if course_code else ("name", _normalize_course_name_key(cname)))
            if dedupe_key in out_seen:
                continue
            out_seen.add(dedupe_key)

            out.append({
                "student_id": sid,
                "student_name": sname_map.get(sid, ""),
                "course_name": cname,
                "course_code": course_code,
                "units": units,
                "attempts": attempts,
                "best_grade_display": best_grade_display,
                "best_semester": best_semester,
                "reason": reason,
                "reason_label": reason_label,
            })
    return out


@students_bp.route("/uncompleted_courses_report")
@role_required("admin", "admin_main", "head_of_department", "supervisor")
def uncompleted_courses_report_api():
    """تقرير: المقررات غير المنجزة لطالب واحد مع تصنيف السبب (غير مسجل/راسب)."""
    sid = normalize_sid(request.args.get("student_id"))
    reason = (request.args.get("reason") or "").strip().lower() or None
    q = (request.args.get("q") or "").strip() or None
    if reason and reason not in ("failed", "not_registered"):
        return jsonify({"status": "error", "message": "reason يجب أن تكون failed أو not_registered"}), 400
    if not sid:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400
    with get_connection() as conn:
        allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed_student_ids is not None and sid not in allowed_student_ids:
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        items = _classified_uncompleted_items(conn, student_id=sid, course_name_like=q, reason_filter=reason)
        items = sorted(items, key=lambda x: (x.get("course_name") or ""))
    summary = {
        "total_uncompleted": len(items),
        "failed_count": sum(1 for i in items if i.get("reason") == "failed"),
        "not_registered_count": sum(1 for i in items if i.get("reason") == "not_registered"),
    }
    return jsonify({"status": "ok", "student_id": sid, "summary": summary, "items": items})


@students_bp.route("/uncompleted_courses_report/excel")
@role_required("admin", "admin_main", "head_of_department", "supervisor")
def uncompleted_courses_report_excel():
    sid = normalize_sid(request.args.get("student_id"))
    r = uncompleted_courses_report_api()
    if isinstance(r, tuple):
        # propagate error status codes (e.g. 403)
        return r[0], r[1]
    payload = r[0].get_json() if isinstance(r, tuple) else r.get_json()
    items = payload.get("items", []) if payload else []
    df = pd.DataFrame(items or [])
    # ترتيب أعمدة ودية
    cols = ["student_id", "student_name", "course_name", "course_code", "units", "reason_label", "best_grade_display", "attempts", "best_semester"]
    if not df.empty:
        keep = [c for c in cols if c in df.columns] + [c for c in df.columns if c not in cols]
        df = df[keep]
    return excel_response_from_df(df, filename_prefix=f"uncompleted_courses_{sid or 'student'}")


@students_bp.route("/uncompleted_courses_report/pdf")
@role_required("admin", "admin_main", "head_of_department", "supervisor")
def uncompleted_courses_report_pdf():
    sid = normalize_sid(request.args.get("student_id"))
    r = uncompleted_courses_report_api()
    if isinstance(r, tuple):
        # propagate error status codes (e.g. 403)
        return r[0], r[1]
    payload = r[0].get_json() if isinstance(r, tuple) else r.get_json()
    items = payload.get("items", []) if payload else []
    rows_html = ""
    for it in items:
        rows_html += (
            "<tr>"
            f"<td>{_h(it.get('course_name'))}</td>"
            f"<td>{_h(it.get('course_code'))}</td>"
            f"<td style='text-align:center'>{_h(it.get('units'))}</td>"
            f"<td style='text-align:center'>{_h(it.get('reason_label'))}</td>"
            f"<td style='text-align:center'>{_h(it.get('best_grade_display'))}</td>"
            f"<td style='text-align:center'>{_h(it.get('attempts'))}</td>"
            f"<td>{_h(it.get('best_semester'))}</td>"
            "</tr>"
        )
    title = f"تقرير المقررات غير المنجزة للطالب ({sid})"
    html = f"""
    <html dir="rtl" lang="ar">
    <head>
      <meta charset="utf-8"/>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 12px; }}
        h2 {{ margin: 0 0 10px 0; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
        th, td {{ border: 1px solid #999; padding: 5px; }}
        th {{ background: #f2f2f2; }}
      </style>
    </head>
    <body>
      <h2>{_h(title)}</h2>
      <p>المقرر غير المنجز يشمل: غير مسجل، أو مسجل مع أفضل نتيجة أقل من 50.</p>
      <table>
        <thead>
          <tr>
            <th>المقرر</th><th>الرمز</th><th>الوحدات</th><th>التصنيف</th><th>أفضل درجة</th><th>المحاولات</th><th>آخر فصل (مرجعي)</th>
          </tr>
        </thead>
        <tbody>
          {rows_html or "<tr><td colspan='7' style='text-align:center'>لا توجد بيانات</td></tr>"}
        </tbody>
      </table>
    </body>
    </html>
    """
    return pdf_response_from_html(html, filename_prefix=f"uncompleted_courses_{sid or 'student'}")


@students_bp.route("/not_registered_courses_report")
@role_required("admin", "admin_main", "head_of_department", "supervisor")
def not_registered_courses_report_api():
    """
    تقرير عام: المقررات غير المسجل بها (من الخطة/قائمة المقررات) حسب أفضلية التصنيف.
    """
    course_name = (request.args.get("course_name") or "").strip() or None
    min_count = request.args.get("min_count")
    try:
        min_count = int(min_count) if min_count not in (None, "") else 0
    except Exception:
        min_count = 0
    include_students = (request.args.get("include_students") or "").strip().lower() in ("1", "true", "yes")

    with get_connection() as conn:
        allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed_student_ids is not None and not allowed_student_ids:
            return jsonify({"status": "ok", "summary": [], "items": [] if include_students else []})
        items = _classified_uncompleted_items(
            conn,
            student_ids=None if allowed_student_ids is None else list(allowed_student_ids),
            course_name_like=course_name,
            reason_filter="not_registered",
        )

    by_course = {}
    for it in items:
        ck = (it.get("course_name") or "", it.get("course_code") or "")
        s = by_course.get(ck)
        if not s:
            s = {
                "course_name": ck[0],
                "course_code": ck[1],
                "units": int(it.get("units") or 0),
                "not_registered_count": 0,
            }
            by_course[ck] = s
        s["not_registered_count"] += 1

    summary = list(by_course.values())
    if min_count and min_count > 0:
        summary = [s for s in summary if int(s.get("not_registered_count") or 0) >= min_count]
    summary = sorted(summary, key=lambda x: (-(int(x.get("not_registered_count") or 0)), x.get("course_name") or ""))

    payload = {"status": "ok", "summary": summary}
    if include_students:
        payload["items"] = sorted(
            items,
            key=lambda x: (x.get("course_name") or "", x.get("student_name") or "", x.get("student_id") or ""),
        )
    return jsonify(payload)


@students_bp.route("/not_registered_courses_report/excel")
@role_required("admin", "admin_main", "head_of_department", "supervisor")
def not_registered_courses_report_excel():
    course_name = (request.args.get("course_name") or "").strip() or None
    min_count = request.args.get("min_count")
    try:
        min_count = int(min_count) if min_count not in (None, "") else 0
    except Exception:
        min_count = 0
    with get_connection() as conn:
        allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed_student_ids is not None and not allowed_student_ids:
            return excel_response_from_frames({"Summary": pd.DataFrame([]), "Students": pd.DataFrame([])}, filename_prefix="not_registered_courses_report")
        items = _classified_uncompleted_items(
            conn,
            student_ids=None if allowed_student_ids is None else list(allowed_student_ids),
            course_name_like=course_name,
            reason_filter="not_registered",
        )
    by_course = {}
    for it in items:
        ck = (it.get("course_name") or "", it.get("course_code") or "")
        s = by_course.get(ck)
        if not s:
            s = {"course_name": ck[0], "course_code": ck[1], "units": int(it.get("units") or 0), "not_registered_count": 0}
            by_course[ck] = s
        s["not_registered_count"] += 1
    summary = list(by_course.values())
    if min_count and min_count > 0:
        summary = [s for s in summary if int(s.get("not_registered_count") or 0) >= min_count]
    summary = sorted(summary, key=lambda x: (-(int(x.get("not_registered_count") or 0)), x.get("course_name") or ""))
    df_summary = pd.DataFrame(summary or [])
    df_items = pd.DataFrame(sorted(items, key=lambda x: (x.get("course_name") or "", x.get("student_name") or "")) or [])
    return excel_response_from_frames({"Summary": df_summary, "Students": df_items}, filename_prefix="not_registered_courses_report")


@students_bp.route("/not_registered_courses_report/pdf")
@role_required("admin", "admin_main", "head_of_department", "supervisor")
def not_registered_courses_report_pdf():
    course_name = (request.args.get("course_name") or "").strip() or None
    min_count = request.args.get("min_count")
    try:
        min_count = int(min_count) if min_count not in (None, "") else 0
    except Exception:
        min_count = 0
    include_students = (request.args.get("include_students") or "").strip().lower() in ("1", "true", "yes")
    with get_connection() as conn:
        allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed_student_ids is not None and not allowed_student_ids:
            html = "<html dir='rtl' lang='ar'><body style='font-family:Arial,sans-serif;'><h2>تقرير المقررات غير المسجل بها</h2><p>لا توجد بيانات ضمن نطاق صلاحياتك.</p></body></html>"
            return pdf_response_from_html(html, filename_prefix="not_registered_courses_report")
        items = _classified_uncompleted_items(
            conn,
            student_ids=None if allowed_student_ids is None else list(allowed_student_ids),
            course_name_like=course_name,
            reason_filter="not_registered",
        )
    by_course = {}
    for it in items:
        ck = (it.get("course_name") or "", it.get("course_code") or "")
        s = by_course.get(ck)
        if not s:
            s = {"course_name": ck[0], "course_code": ck[1], "units": int(it.get("units") or 0), "not_registered_count": 0}
            by_course[ck] = s
        s["not_registered_count"] += 1
    summary = list(by_course.values())
    if min_count and min_count > 0:
        summary = [s for s in summary if int(s.get("not_registered_count") or 0) >= min_count]
    summary = sorted(summary, key=lambda x: (-(int(x.get("not_registered_count") or 0)), x.get("course_name") or ""))

    sum_rows = "".join(
        "<tr>"
        f"<td>{_h(s.get('course_name'))}</td>"
        f"<td>{_h(s.get('course_code'))}</td>"
        f"<td style='text-align:center'>{_h(s.get('units'))}</td>"
        f"<td style='text-align:center'><strong>{_h(s.get('not_registered_count'))}</strong></td>"
        "</tr>"
        for s in summary
    )
    det_rows = ""
    if include_students:
        for it in sorted(items, key=lambda x: (x.get("course_name") or "", x.get("student_name") or "", x.get("student_id") or "")):
            det_rows += (
                "<tr>"
                f"<td>{_h(it.get('course_name'))}</td>"
                f"<td>{_h(it.get('course_code'))}</td>"
                f"<td>{_h(it.get('student_id'))}</td>"
                f"<td>{_h(it.get('student_name'))}</td>"
                "</tr>"
            )
    html = f"""
    <html dir="rtl" lang="ar">
    <head>
      <meta charset="utf-8"/>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 12px; }}
        h2 {{ margin: 0 0 10px 0; }}
        h3 {{ margin: 16px 0 8px 0; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
        th, td {{ border: 1px solid #999; padding: 5px; }}
        th {{ background: #f2f2f2; }}
      </style>
    </head>
    <body>
      <h2>تقرير المقررات غير المسجل بها</h2>
      <p>يعرض المقررات الموجودة بالخطة/قائمة المقررات والتي لا توجد لها أي محاولة في السجل الأكاديمي للطالب.</p>
      <h3>ملخص حسب المقرر</h3>
      <table>
        <thead><tr><th>المقرر</th><th>الرمز</th><th>الوحدات</th><th>عدد غير المسجلين</th></tr></thead>
        <tbody>{sum_rows or "<tr><td colspan='4' style='text-align:center'>لا توجد بيانات</td></tr>"}</tbody>
      </table>
      {"<h3>تفصيل الطلبة</h3><table><thead><tr><th>المقرر</th><th>الرمز</th><th>رقم الطالب</th><th>الاسم</th></tr></thead><tbody>"+det_rows+"</tbody></table>" if include_students else ""}
    </body>
    </html>
    """
    return pdf_response_from_html(html, filename_prefix="not_registered_courses_report")


@students_bp.route("/failed_courses_report")
@role_required("admin", "admin_main", "head_of_department", "supervisor")
def failed_courses_report_api():
    """
    تقرير عام: المقررات التي رسب فيها الطلبة.
    فلاتر:
      - course_name: بحث جزئي بالاسم/الرمز
      - min_failed: حد أدنى لعدد الراسبين في المقرر (ملخص)
      - include_students=1 لإرجاع قائمة الطلبة التفصيلية
    """
    course_name = (request.args.get("course_name") or "").strip() or None
    min_failed = request.args.get("min_failed")
    try:
        min_failed = int(min_failed) if min_failed not in (None, "") else 0
    except Exception:
        min_failed = 0
    include_students = (request.args.get("include_students") or "").strip().lower() in ("1", "true", "yes")

    with get_connection() as conn:
        allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed_student_ids is not None and not allowed_student_ids:
            if include_students:
                return jsonify({"status": "ok", "summary": [], "items": []})
            return jsonify({"status": "ok", "summary": []})

        best = _best_grades_map(
            conn,
            student_id=None,
            student_ids=allowed_student_ids,
            course_name_like=course_name,
        )
    failed_items = [v for v in best.values() if not v.get("passed")]

    # summary by course
    by_course = {}
    for it in failed_items:
        ck = (it.get("course_name") or "", it.get("course_code") or "")
        s = by_course.get(ck)
        if not s:
            s = {
                "course_name": it.get("course_name") or "",
                "course_code": it.get("course_code") or "",
                "units": int(it.get("units") or 0),
                "failed_count": 0,
            }
            by_course[ck] = s
        s["failed_count"] += 1
        if (s.get("units") or 0) <= 0 and (it.get("units") or 0) > 0:
            s["units"] = int(it.get("units") or 0)

    summary = list(by_course.values())
    if min_failed and min_failed > 0:
        summary = [s for s in summary if int(s.get("failed_count") or 0) >= min_failed]
    summary = sorted(summary, key=lambda x: (-(int(x.get("failed_count") or 0)), x.get("course_name") or ""))

    payload = {"status": "ok", "summary": summary}
    if include_students:
        payload["items"] = sorted(
            failed_items,
            key=lambda x: (x.get("course_name") or "", x.get("student_name") or "", x.get("student_id") or ""),
        )
    return jsonify(payload)


@students_bp.route("/failed_courses_report/excel")
@role_required("admin", "admin_main", "head_of_department", "supervisor")
def failed_courses_report_excel():
    course_name = (request.args.get("course_name") or "").strip() or None
    min_failed = request.args.get("min_failed")
    try:
        min_failed = int(min_failed) if min_failed not in (None, "") else 0
    except Exception:
        min_failed = 0
    with get_connection() as conn:
        allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed_student_ids is not None and not allowed_student_ids:
            df_summary = pd.DataFrame([])
            df_items = pd.DataFrame([])
            return excel_response_from_frames(
                {"Summary": df_summary, "Students": df_items},
                filename_prefix="failed_courses_report",
            )
        best = _best_grades_map(
            conn,
            student_id=None,
            student_ids=allowed_student_ids,
            course_name_like=course_name,
        )
    failed_items = [v for v in best.values() if not v.get("passed")]
    # build frames
    # summary
    by_course = {}
    for it in failed_items:
        ck = (it.get("course_name") or "", it.get("course_code") or "")
        s = by_course.get(ck)
        if not s:
            s = {"course_name": ck[0], "course_code": ck[1], "units": int(it.get("units") or 0), "failed_count": 0}
            by_course[ck] = s
        s["failed_count"] += 1
        if (s.get("units") or 0) <= 0 and (it.get("units") or 0) > 0:
            s["units"] = int(it.get("units") or 0)
    summary = list(by_course.values())
    if min_failed and min_failed > 0:
        summary = [s for s in summary if int(s.get("failed_count") or 0) >= min_failed]
    summary = sorted(summary, key=lambda x: (-(int(x.get("failed_count") or 0)), x.get("course_name") or ""))

    df_summary = pd.DataFrame(summary or [])
    df_items = pd.DataFrame(sorted(failed_items, key=lambda x: (x.get("course_name") or "", x.get("student_name") or "")) or [])
    return excel_response_from_frames(
        {"Summary": df_summary, "Students": df_items},
        filename_prefix="failed_courses_report",
    )


@students_bp.route("/failed_courses_report/pdf")
@role_required("admin", "admin_main", "head_of_department", "supervisor")
def failed_courses_report_pdf():
    course_name = (request.args.get("course_name") or "").strip() or None
    min_failed = request.args.get("min_failed")
    try:
        min_failed = int(min_failed) if min_failed not in (None, "") else 0
    except Exception:
        min_failed = 0
    include_students = (request.args.get("include_students") or "").strip().lower() in ("1", "true", "yes")

    with get_connection() as conn:
        allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
        if allowed_student_ids is not None and not allowed_student_ids:
            # بدون بيانات: صفحة PDF فارغة تجنب أي تسريب
            html = f"""
            <html dir="rtl" lang="ar"><body style="font-family:Arial,sans-serif;">
              <h2>تقرير مقررات الرسوب</h2>
              <p>لا توجد بيانات ضمن نطاق صلاحياتك.</p>
            </body></html>
            """
            return pdf_response_from_html(html, filename_prefix="failed_courses_report")

        best = _best_grades_map(
            conn,
            student_id=None,
            student_ids=allowed_student_ids,
            course_name_like=course_name,
        )
    failed_items = [v for v in best.values() if not v.get("passed")]
    by_course = {}
    for it in failed_items:
        ck = (it.get("course_name") or "", it.get("course_code") or "")
        s = by_course.get(ck)
        if not s:
            s = {"course_name": ck[0], "course_code": ck[1], "units": int(it.get("units") or 0), "failed_count": 0}
            by_course[ck] = s
        s["failed_count"] += 1
        if (s.get("units") or 0) <= 0 and (it.get("units") or 0) > 0:
            s["units"] = int(it.get("units") or 0)
    summary = list(by_course.values())
    if min_failed and min_failed > 0:
        summary = [s for s in summary if int(s.get("failed_count") or 0) >= min_failed]
    summary = sorted(summary, key=lambda x: (-(int(x.get("failed_count") or 0)), x.get("course_name") or ""))

    sum_rows = ""
    for s in summary:
        sum_rows += (
            "<tr>"
            f"<td>{_h(s.get('course_name'))}</td>"
            f"<td>{_h(s.get('course_code'))}</td>"
            f"<td style='text-align:center'>{_h(s.get('units'))}</td>"
            f"<td style='text-align:center'><strong>{_h(s.get('failed_count'))}</strong></td>"
            "</tr>"
        )

    det_rows = ""
    if include_students:
        for it in sorted(failed_items, key=lambda x: (x.get("course_name") or "", x.get("student_name") or "", x.get("student_id") or "")):
            det_rows += (
                "<tr>"
                f"<td>{_h(it.get('course_name'))}</td>"
                f"<td>{_h(it.get('course_code'))}</td>"
                f"<td>{_h(it.get('student_id'))}</td>"
                f"<td>{_h(it.get('student_name'))}</td>"
                f"<td style='text-align:center'>{_h(it.get('best_grade_display'))}</td>"
                f"<td style='text-align:center'>{_h(it.get('attempts'))}</td>"
                "</tr>"
            )

    html = f"""
    <html dir="rtl" lang="ar">
    <head>
      <meta charset="utf-8"/>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 12px; }}
        h2 {{ margin: 0 0 10px 0; }}
        h3 {{ margin: 16px 0 8px 0; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
        th, td {{ border: 1px solid #999; padding: 5px; }}
        th {{ background: #f2f2f2; }}
      </style>
    </head>
    <body>
      <h2>تقرير مقررات الرسوب</h2>
      <p>يعرض المقررات التي توجد لها محاولات في كشف الدرجات لكن أفضل نتيجة فيها أقل من 50.</p>
      <h3>ملخص حسب المقرر</h3>
      <table>
        <thead><tr><th>المقرر</th><th>الرمز</th><th>الوحدات</th><th>عدد غير المنجزة</th></tr></thead>
        <tbody>{sum_rows or "<tr><td colspan='4' style='text-align:center'>لا توجد بيانات</td></tr>"}</tbody>
      </table>
      {"<h3>تفصيل الطلبة</h3><table><thead><tr><th>المقرر</th><th>الرمز</th><th>رقم الطالب</th><th>الاسم</th><th>أفضل درجة</th><th>المحاولات</th></tr></thead><tbody>"+det_rows+"</tbody></table>" if include_students else ""}
    </body>
    </html>
    """
    return pdf_response_from_html(html, filename_prefix="failed_courses_report")


@students_bp.route("/registration_changes_report/delete", methods=["POST"])
@role_required("admin")
def registration_changes_report_delete():
    """
    حذف سجلات من registration_changes_log بناءً على نفس الفلاتر المستخدمة في التقرير.
    مخصص لحذف العمليات التجريبية (ينصح بالحذر لأنه لا يمكن التراجع).
    يقبل في الجسم JSON نفس الحقول: date_from, date_to, student_id, action, course_name.
    """
    data = request.get_json(force=True) or {}
    date_from = (data.get("date_from") or "").strip() or None
    date_to = (data.get("date_to") or "").strip() or None
    student_id = (data.get("student_id") or "").strip() or None
    action = (data.get("action") or "").strip() or None
    course_name = (data.get("course_name") or "").strip() or None

    with get_connection() as conn:
        # نجلب أولاً المعرفات المطابقة ثم نحذفها
        items = _registration_changes_report_items(
            conn, date_from=date_from, date_to=date_to,
            student_id=student_id, action=action, course_name_like=course_name
        )
        ids = [it.get("id") for it in items if it.get("id") is not None]
        deleted_count = 0
        if ids:
            cur = conn.cursor()
            placeholders = ",".join("?" for _ in ids)
            cur.execute(f"DELETE FROM registration_changes_log WHERE id IN ({placeholders})", ids)
            conn.commit()
            deleted_count = cur.rowcount if cur.rowcount is not None else len(ids)
    return jsonify({"status": "ok", "deleted": int(deleted_count)}), 200


# -----------------------------
# مساعدة: تطبيع معرّف الطالب
# -----------------------------
def normalize_sid(sid):
    if sid is None:
        return ""
    return str(sid).strip()


def _get_allowed_student_ids_for_role(conn, user_role: str) -> set:
    """
    تُرجع set بأرقام الطلاب المسموح عرضهم/تصديرهم حسب role الحالي.
    - admin_main / admin: None يعني unrestricted
    - student: set يحتوي على سجله فقط
    - supervisor: طلابه فقط عبر student_supervisor
    - instructor: طلاب مقررات الفصل الحالي عبر schedule + registrations
    """
    role = (user_role or "").strip()
    if role in ("admin_main", "admin"):
        return None

    cur = conn.cursor()

    if role == "student":
        sid_session = normalize_sid(session.get("student_id") or session.get("user"))
        return {sid_session} if sid_session else set()

    is_supervisor = (role == "supervisor") or (role == "instructor" and int(session.get("is_supervisor") or 0) == 1)
    if is_supervisor:
        instructor_id = session.get("instructor_id")
        if not instructor_id:
            return set()
        rows = cur.execute(
            "SELECT student_id FROM student_supervisor WHERE instructor_id = ?",
            (instructor_id,),
        ).fetchall()
        return {normalize_sid(r[0]) for r in rows if r and r[0]}

    if role == "instructor":
        instructor_id = session.get("instructor_id")
        if not instructor_id:
            return set()
        instr_row = cur.execute(
            "SELECT name FROM instructors WHERE id = ? LIMIT 1",
            (instructor_id,),
        ).fetchone()
        instructor_name = instr_row[0] if instr_row else ""
        if not instructor_name:
            return set()

        term_name, term_year = get_current_term(conn=conn)
        semester_label = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()
        if not semester_label:
            return set()

        rows = cur.execute(
            """
            SELECT DISTINCT r.student_id
            FROM schedule s
            JOIN registrations r ON r.course_name = s.course_name
            WHERE s.semester = ?
              AND s.instructor = ?
              AND COALESCE(s.course_name,'') <> ''
            """,
            (semester_label, instructor_name),
        ).fetchall()
        return {normalize_sid(r[0]) for r in rows if r and r[0]}

    # أي role غير معروف: نمنع (بدون تسريب)
    return set()

# -----------------------------
# CRUD أساسي للطلاب
# -----------------------------
@students_bp.route("/list")
@login_required
def list_students():
    """جلب قائمة الطلاب. معاملات: active_only=1، enrollment_status=active|withdrawn|suspended|graduated، join_term، join_year."""
    try:
        from backend.core.exceptions import AppException

        user_role = session.get("user_role")
        with get_connection() as conn:
            allowed_student_ids = _get_allowed_student_ids_for_role(conn, user_role)

        if allowed_student_ids is not None and not allowed_student_ids:
            return jsonify([])

        students = students_filtered_from_request(request)
        if allowed_student_ids is not None:
            students = [s for s in students if normalize_sid(s.get("student_id")) in allowed_student_ids]
        # تحويل إلى كائنات Student للتوافق مع الكود القديم مع إضافة حالة القيد كحقول إضافية
        students_objects = []
        for s in students:
            obj = Student(s["student_id"], s["student_name"])
            # إرفاق حالة القيد وحقولها كخصائص إضافية
            setattr(obj, "enrollment_status", s.get("enrollment_status", "active"))
            setattr(obj, "status_changed_at", s.get("status_changed_at"))
            setattr(obj, "status_reason", s.get("status_reason", ""))
            setattr(obj, "status_changed_term", s.get("status_changed_term", ""))
            setattr(obj, "status_changed_year", s.get("status_changed_year", ""))
            setattr(obj, "graduation_plan", s.get("graduation_plan", ""))
            setattr(obj, "join_term", s.get("join_term", ""))
            setattr(obj, "join_year", s.get("join_year", ""))
            students_objects.append(obj)
        return jsonify([s.__dict__ for s in students_objects])
    except AppException as e:
        # fallback مباشر من قاعدة البيانات إذا فشل Service Layer
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    "SELECT student_id, COALESCE(student_name,'') AS student_name FROM students ORDER BY student_name, student_id"
                ).fetchall()
            user_role = session.get("user_role")
            with get_connection() as conn:
                allowed_student_ids = _get_allowed_student_ids_for_role(conn, user_role)
            if allowed_student_ids is None:
                return jsonify([{"student_id": r[0], "student_name": r[1]} for r in rows])
            return jsonify(
                [{"student_id": r[0], "student_name": r[1]} for r in rows if normalize_sid(r[0]) in allowed_student_ids]
            )
        except Exception:
            raise
    except Exception as e:
        # fallback مباشر من قاعدة البيانات بدلاً من كسر صفحة كشف الدرجات
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    "SELECT student_id, COALESCE(student_name,'') AS student_name FROM students ORDER BY student_name, student_id"
                ).fetchall()
            user_role = session.get("user_role")
            with get_connection() as conn:
                allowed_student_ids = _get_allowed_student_ids_for_role(conn, user_role)
            if allowed_student_ids is None:
                return jsonify([{"student_id": r[0], "student_name": r[1]} for r in rows])
            return jsonify(
                [{"student_id": r[0], "student_name": r[1]} for r in rows if normalize_sid(r[0]) in allowed_student_ids]
            )
        except Exception:
            from backend.core.exceptions import DatabaseError
            raise DatabaseError(f"فشل جلب قائمة الطلاب: {str(e)}")


@students_bp.route("/graduates")
@login_required
def list_graduates():
    """قائمة الخريجين: الاسم، الرقم الدراسي، الهاتف، سنة التخرج، المعدل التراكمي."""
    try:
        from backend.services.grades import _load_transcript_data
        with get_connection() as conn:
            cur = conn.cursor()
            cols = [row[1] for row in cur.execute("PRAGMA table_info(students)").fetchall()]
            has_status = "enrollment_status" in cols
            has_phone = "phone" in cols
            if not has_status:
                return jsonify([])
            sel = "student_id, student_name, status_changed_at"
            if has_phone:
                sel += ", phone"
            rows = cur.execute(f"""
                SELECT {sel}
                FROM students
                WHERE COALESCE(enrollment_status, 'active') = 'graduated'
                ORDER BY status_changed_at DESC, student_name, student_id
            """).fetchall()
        result = []
        for r in rows:
            sid = r["student_id"]
            try:
                tr = _load_transcript_data(sid)
                gpa = tr.get("cumulative_gpa")
            except Exception:
                gpa = None
            year = None
            if r.get("status_changed_at"):
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(r["status_changed_at"].replace("Z", "+00:00"))
                    year = dt.year
                except Exception:
                    pass
            result.append({
                "student_id": sid,
                "student_name": r["student_name"] or "",
                "phone": (r["phone"] or "") if has_phone else "",
                "graduation_year": year,
                "cumulative_gpa": gpa,
            })
        return jsonify(result)
    except Exception as e:
        from backend.core.exceptions import DatabaseError
        raise DatabaseError(f"فشل جلب قائمة الخريجين: {str(e)}")


@students_bp.route("/add", methods=["POST"])
@login_required
def add_student():
    """إضافة طالب جديد - يستخدم Service Layer"""
    try:
        from backend.core.services import StudentService
        from backend.core.exceptions import AppException
        
        data = request.get_json(force=True) or {}
        sid = data.get("student_id")
        name = data.get("student_name", "") or ""
        graduation_plan = (data.get("graduation_plan") or "").strip()
        join_term = (data.get("join_term") or "").strip()
        join_year = (data.get("join_year") or "").strip()
        
        result = StudentService.add_student(
            sid, name,
            graduation_plan=graduation_plan,
            join_term=join_term,
            join_year=join_year,
        )
        return jsonify(result), 200
    except AppException as e:
        # يتم التعامل مع AppException تلقائياً من خلال error handlers
        raise
    except Exception as e:
        from backend.core.exceptions import DatabaseError
        raise DatabaseError(f"فشل إضافة الطالب: {str(e)}")


@students_bp.route("/update_status", methods=["POST"])
@role_required("admin", "admin_main", "head_of_department")
def update_student_status():
    """تحديث حالة قيد الطالب (مسجَّل، سحب الملف، موقوف قيده، خريج) عبر Service Layer"""
    try:
        from backend.core.services import StudentService
        from backend.core.exceptions import AppException

        data = request.get_json(force=True) or {}
        sid = data.get("student_id")
        status = data.get("enrollment_status") or data.get("status")
        changed_at = data.get("status_changed_at") or data.get("changed_at")
        reason = data.get("status_reason") or data.get("reason", "")
        phone = data.get("phone") or ""
        status_changed_term = (data.get("status_changed_term") or data.get("action_term") or "").strip()
        status_changed_year = (data.get("status_changed_year") or data.get("action_year") or "").strip()

        result = StudentService.update_enrollment_status(
            student_id=sid,
            status=status,
            changed_at=changed_at,
            reason=reason or "",
            phone=phone,
            status_changed_term=status_changed_term,
            status_changed_year=status_changed_year,
        )
        return jsonify(result), 200
    except AppException:
        raise
    except Exception as e:
        from backend.core.exceptions import DatabaseError
        raise DatabaseError(f"فشل تحديث حالة قيد الطالب: {str(e)}")

@students_bp.route("/delete", methods=["POST"])
@login_required
def delete_student():
    """حذف طالب - يستخدم Service Layer"""
    try:
        from backend.core.services import StudentService
        from backend.core.exceptions import AppException
        
        data = request.get_json(force=True) or {}
        sid = data.get("student_id")
        
        result = StudentService.delete_student(sid)
        # حذف البيانات المرتبطة (للتوافق مع الكود القديم)
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM registrations WHERE student_id = ?", (sid,))
                cur.execute("DELETE FROM grades WHERE student_id = ?", (sid,))
                cur.execute("DELETE FROM grade_audit WHERE student_id = ?", (sid,))
                conn.commit()
        except Exception:
            pass  # تجاهل الأخطاء في الحذف المرتبط
        
        return jsonify(result), 200
    except AppException as e:
        # يتم التعامل مع AppException تلقائياً من خلال error handlers
        raise
    except Exception as e:
        from backend.core.exceptions import DatabaseError
        raise DatabaseError(f"فشل حذف الطالب: {str(e)}")

# -----------------------------
# التسجيلات
# -----------------------------
@students_bp.route("/save_registrations", methods=["POST"])
@role_required("admin")
def save_registrations():
    data = request.get_json(force=True) or {}
    sid = normalize_sid(data.get("student_id"))
    override_reason = (data.get("override_reason") or "").strip()
    sig = data.get("signature") or {}
    student_signed = bool(sig.get("student_signed")) if isinstance(sig, dict) else bool(data.get("student_signed"))
    signed_at = (sig.get("signed_at") if isinstance(sig, dict) else data.get("signed_at")) or ""
    signature_note = (sig.get("signature_note") if isinstance(sig, dict) else data.get("signature_note")) or ""
    try:
        form_file_id = int((sig.get("form_file_id") if isinstance(sig, dict) else data.get("form_file_id")) or 0) or None
    except Exception:
        form_file_id = None
    try:
        form_version_id = int((sig.get("form_version_id") if isinstance(sig, dict) else data.get("form_version_id")) or 0) or None
    except Exception:
        form_version_id = None
    courses = data.get("courses")
    if courses is None:
        courses = data.get("registrations", [])
    if courses is None:
        courses = []
    if not sid:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400
    if not isinstance(courses, list):
        return jsonify({"status": "error", "message": "courses/registrations يجب أن تكون قائمة"}), 400

    old_courses = set()
    # منع تسجيل طالب غير فعّال (سحب ملف، موقوف قيده، خريج)
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            # قراءة التسجيلات الحالية لهذا الطالب قبل التعديل لاستخراج الإضافات/الإسقاطات
            old_rows = cur.execute(
                "SELECT course_name FROM registrations WHERE student_id = ?",
                (sid,),
            ).fetchall()
            old_courses = {r[0] for r in old_rows}
            cols = [r[1] for r in cur.execute("PRAGMA table_info(students)").fetchall()]
            if "enrollment_status" in cols:
                row = cur.execute(
                    "SELECT COALESCE(enrollment_status, 'active') FROM students WHERE student_id = ?",
                    (sid,),
                ).fetchone()
                if row and (row[0] or "active") != "active":
                    return jsonify({
                        "status": "error",
                        "message": "لا يمكن تعديل التسجيلات لطالب غير مسجّل (حالة القيد: سحب ملف أو موقوف قيده أو خريج).",
                    }), 400
    except Exception:
        pass

    # Deduplicate provided courses while preserving order to avoid inserting duplicates
    seen = set()
    deduped = []
    for c in courses:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    courses = deduped

    try:
        with get_connection() as conn:
            cur = conn.cursor()
            prereq_eval = evaluate_courses_prereqs(cur, sid, courses, old_courses)
            drop_violations = prereq_eval.get("drop_violations") or []
            if drop_violations:
                return jsonify(
                    {
                        "status": "error",
                        "code": "PREREQ_CO_DROP",
                        "message": drop_violations[0].get(
                            "message_ar",
                            "لا يمكن إبقاء المقرر التابع وإسقاط متطلبه وحده.",
                        ),
                        "drop_violations": drop_violations,
                    }
                ), 400
            blocked = prereq_eval.get("blocked") or {}
            if blocked:
                return jsonify({"status": "error", "message": "بعض المتطلبات غير مستوفاة", "blocked": blocked}), 400

            # التحقق من حد الوحدات 12-19 (إلزامي) مع استثناء للأدمن فقط بشرط سبب
            try:
                total_units = 0
                if courses:
                    placeholders = ",".join("?" for _ in courses)
                    rows_u = cur.execute(
                        f"SELECT course_name, COALESCE(units,0) AS units FROM courses WHERE course_name IN ({placeholders})",
                        courses,
                    ).fetchall()
                    units_map = {r[0]: int(r[1] or 0) for r in rows_u}
                    total_units = sum(int(units_map.get(c, 0) or 0) for c in courses)
                out_of_range = (total_units < 12) or (total_units > 19)
                if out_of_range:
                    role = session.get("user_role") or ""
                    if role != "admin":
                        return jsonify({
                            "status": "error",
                            "code": "UNITS_LIMIT",
                            "message": f"لا يمكن حفظ التسجيلات لأن إجمالي الوحدات ({total_units}) خارج المدى المسموح 12-19.",
                            "total_units": total_units,
                        }), 400
                    if not override_reason:
                        return jsonify({
                            "status": "error",
                            "code": "UNITS_OVERRIDE_REQUIRED",
                            "message": f"إجمالي الوحدات ({total_units}) خارج 12-19. أدخل سبب التجاوز للحفظ كأدمن.",
                            "total_units": total_units,
                        }), 400
            except Exception:
                current_app.logger.exception("units limit check failed; continuing without blocking")
                out_of_range = False
                total_units = 0

            try:
                cur.execute("DELETE FROM registrations WHERE student_id = ?", (sid,))
                if courses:
                    cur.executemany(
                        "INSERT INTO registrations (student_id, course_name) VALUES (?,?)",
                        [(sid, c) for c in courses]
                    )

                # حساب الفرق بين القديم والجديد لتسجيل سجل الإضافة/الإسقاط
                new_courses = set(courses)
                added = [c for c in courses if c not in old_courses]
                dropped = [c for c in old_courses if c not in new_courses]

                # جلب معلومات إضافية عن الطالب والمقررات
                try:
                    student_row = cur.execute(
                        "SELECT COALESCE(student_name,'') FROM students WHERE student_id = ?",
                        (sid,),
                    ).fetchone()
                    student_name = student_row[0] if student_row else ""
                except Exception:
                    student_name = ""

                def _get_course_meta(name: str):
                    try:
                        row = cur.execute(
                            "SELECT COALESCE(course_code,''), COALESCE(units,0) FROM courses WHERE course_name = ?",
                            (name,),
                        ).fetchone()
                        if row:
                            return row[0], int(row[1] or 0)
                    except Exception:
                        pass
                    return "", 0

                performed_by = (session.get("user") or "") if "user" in session else ""
                # نحاول حفظ اسم الفصل الحالي في السجل لسهولة التقارير
                try:
                    term_name, term_year = get_current_term(conn=conn)
                    term_label = f"{term_name} {term_year}".strip()
                except Exception:
                    term_label = ""
                now_iso = datetime.datetime.utcnow().isoformat()

                # حفظ/تحديث توثيق التوقيع (للـ "التسجيل الفعلي" للفصل الحالي)
                try:
                    _ensure_registration_signature_tables(cur)
                    form_version_no = 0
                    if form_version_id:
                        try:
                            row_v = cur.execute(
                                "SELECT COALESCE(version_no,0) FROM registration_form_versions WHERE id = ? LIMIT 1",
                                (form_version_id,),
                            ).fetchone()
                            form_version_no = int(row_v[0] or 0) if row_v else 0
                        except Exception:
                            form_version_no = 0
                    if term_label:
                        cur.execute(
                            """
                            INSERT INTO registration_signatures
                            (student_id, term, student_signed, signed_at, signature_note, form_file_id, updated_at, updated_by)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(student_id, term) DO UPDATE SET
                              student_signed=excluded.student_signed,
                              signed_at=excluded.signed_at,
                              signature_note=excluded.signature_note,
                              form_file_id=excluded.form_file_id,
                              updated_at=excluded.updated_at,
                              updated_by=excluded.updated_by
                            """,
                            (
                                sid,
                                term_label,
                                1 if student_signed else 0,
                                (str(signed_at).strip() or None),
                                (str(signature_note).strip() or None),
                                form_file_id,
                                now_iso,
                                performed_by,
                            ),
                        )
                        # حفظ سجل تاريخي حسب نسخة الاستمارة (إن وُجدت)، لإتاحة تتبع توقيع مختلف لكل نسخة/فصل.
                        if form_version_id:
                            cur.execute(
                                """
                                INSERT INTO registration_signature_events
                                (student_id, term, form_version_id, form_version_no, student_signed, signed_at, signature_note, form_file_id, updated_at, updated_by)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(student_id, term, form_version_id) DO UPDATE SET
                                  form_version_no=excluded.form_version_no,
                                  student_signed=excluded.student_signed,
                                  signed_at=excluded.signed_at,
                                  signature_note=excluded.signature_note,
                                  form_file_id=excluded.form_file_id,
                                  updated_at=excluded.updated_at,
                                  updated_by=excluded.updated_by
                                """,
                                (
                                    sid,
                                    term_label,
                                    form_version_id,
                                    form_version_no,
                                    1 if student_signed else 0,
                                    (str(signed_at).strip() or None),
                                    (str(signature_note).strip() or None),
                                    form_file_id,
                                    now_iso,
                                    performed_by,
                                ),
                            )
                except Exception:
                    current_app.logger.exception("failed to upsert registration_signatures in save_registrations")

                try:
                    for cname in added:
                        code, units = _get_course_meta(cname)
                        cur.execute(
                            """
                            INSERT INTO registration_changes_log
                            (student_id, student_name, term, course_name, course_code, units,
                             action, action_phase, action_time, performed_by, reason, notes,
                             prev_state, new_state)
                            VALUES (?, ?, ?, ?, ?, ?, 'add', ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                sid,
                                student_name,
                                term_label,
                                cname,
                                code,
                                units,
                                "manual",
                                now_iso,
                                performed_by,
                                (override_reason if out_of_range else ""),
                                ("units_override" if out_of_range else "bulk_save"),
                                '{"registered": false}',
                                '{"registered": true}',
                            ),
                        )

                    for cname in dropped:
                        code, units = _get_course_meta(cname)
                        cur.execute(
                            """
                            INSERT INTO registration_changes_log
                            (student_id, student_name, term, course_name, course_code, units,
                             action, action_phase, action_time, performed_by, reason, notes,
                             prev_state, new_state)
                            VALUES (?, ?, ?, ?, ?, ?, 'drop', ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                sid,
                                student_name,
                                term_label,
                                cname,
                                code,
                                units,
                                "manual",
                                now_iso,
                                performed_by,
                                (override_reason if out_of_range else ""),
                                ("units_override" if out_of_range else "bulk_save"),
                                '{"registered": true}',
                                '{"registered": false}',
                            ),
                        )
                except Exception:
                    current_app.logger.exception("failed to write registration_changes_log in save_registrations")

                conn.commit()

                # إعادة حساب التعارضات وتحديث جدول conflict_report
                try:
                    from backend.services.students import compute_per_student_conflicts
                    conflicts = compute_per_student_conflicts(conn)
                    # حذف تعارضات الطالب الحالي فقط
                    cur.execute("DELETE FROM conflict_report WHERE student_id = ?", (sid,))
                    # إضافة التعارضات الجديدة للطالب
                    for conf in conflicts:
                        if conf.get('student_id') == sid:
                            cur.execute(
                                "INSERT INTO conflict_report (student_id, day, time, conflicting_sections) VALUES (?,?,?,?)",
                                (conf.get('student_id',''), conf.get('day',''), conf.get('time',''), conf.get('conflicting_sections',''))
                            )
                    conn.commit()
                except Exception as e:
                    current_app.logger.exception("recompute conflict_report failed")

                # تسجيل العملية في سجل النشاط
                try:
                    log_activity(
                        action="save_registrations",
                        details=f"student_id={sid}, courses={','.join(courses)}",
                    )
                except Exception:
                    pass

                return jsonify(
                    {
                        "status": "ok",
                        "message": "تم حفظ التسجيلات",
                        "prereq_warnings": prereq_eval.get("warnings") or [],
                        "prereq_coregister_pairs": prereq_eval.get("coregister_pairs") or [],
                        "prereq_validation": prereq_eval,
                    }
                ), 200
            except Exception as e:
                conn.rollback()
                current_app.logger.exception("insert registrations failed")
                return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        current_app.logger.exception("save_registrations outer failure")
        return jsonify({"status": "error", "message": str(e)}), 500

def _json_no_cache(payload, code: int = 200):
    """استجابة JSON مع منع التخزين المؤقت (تسجيلات فعلية تتغير بعد الحفظ)."""
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    if code != 200:
        return resp, code
    return resp


@students_bp.route("/get_registrations")
@login_required
def get_registrations():
    student_id = normalize_sid(request.args.get("student_id"))
    try:
        with get_connection() as conn:
            cur = conn.cursor()

            # Scope: تقييد الوصول حسب الدور
            user_role = session.get("user_role")
            allowed_student_ids = _get_allowed_student_ids_for_role(conn, user_role)

            # أدوار يجب تقييدها (None يعني unrestricted)
            if allowed_student_ids is not None:
                if user_role == "student":
                    sid_session = normalize_sid(session.get("student_id") or session.get("user"))
                    if not sid_session:
                        return _json_no_cache([])
                    if student_id and student_id != sid_session:
                        return _json_no_cache([], 403)
                    student_id = sid_session

                # منع إرجاع جميع التسجيلات لهذه الأدوار
                if not student_id:
                    return _json_no_cache([])

                if not allowed_student_ids or student_id not in allowed_student_ids:
                    return _json_no_cache([])

                rows = cur.execute(
                    "SELECT course_name FROM registrations WHERE student_id = ?",
                    (student_id,),
                ).fetchall()
                return _json_no_cache([r[0] for r in rows])

            # unrestricted (admin/admin_main)
            if student_id:
                rows = cur.execute(
                    "SELECT course_name FROM registrations WHERE student_id = ?",
                    (student_id,),
                ).fetchall()
                return _json_no_cache([r[0] for r in rows])

            rows = cur.execute(
                "SELECT student_id, course_name FROM registrations",
            ).fetchall()
            return _json_no_cache([{"student_id": r[0], "course_name": r[1]} for r in rows])
    except Exception:
        current_app.logger.exception("get_registrations failed")
        return _json_no_cache([])

@students_bp.route("/delete_registrations", methods=["POST"])
@role_required("admin")
def delete_registrations():
    data = request.get_json(force=True) or {}
    sid = normalize_sid(data.get("student_id"))
    if not sid:
        return jsonify({"status":"error","message":"student_id مطلوب"}), 400
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            rows = cur.execute(
                "SELECT course_name FROM registrations WHERE student_id = ?",
                (sid,),
            ).fetchall()
            existing = [r[0] for r in rows]

            # سجل إسقاط لكل مقرر قبل الحذف
            try:
                student_row = cur.execute(
                    "SELECT COALESCE(student_name,'') FROM students WHERE student_id = ?",
                    (sid,),
                ).fetchone()
                student_name = student_row[0] if student_row else ""
            except Exception:
                student_name = ""

            def _get_course_meta(name: str):
                try:
                    row = cur.execute(
                        "SELECT COALESCE(course_code,''), COALESCE(units,0) FROM courses WHERE course_name = ?",
                        (name,),
                    ).fetchone()
                    if row:
                        return row[0], int(row[1] or 0)
                except Exception:
                    pass
                return "", 0

            performed_by = (session.get("user") or "") if "user" in session else ""
            # نحاول حفظ اسم الفصل الحالي في السجل
            try:
                term_name, term_year = get_current_term(conn=conn)
                term_label = f"{term_name} {term_year}".strip()
            except Exception:
                term_label = ""
            now_iso = datetime.datetime.utcnow().isoformat()

            try:
                for cname in existing:
                    code, units = _get_course_meta(cname)
                    cur.execute(
                        """
                        INSERT INTO registration_changes_log
                        (student_id, student_name, term, course_name, course_code, units,
                         action, action_phase, action_time, performed_by, reason, notes,
                         prev_state, new_state)
                        VALUES (?, ?, ?, ?, ?, ?, 'drop', ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            sid,
                            student_name,
                            term_label,
                            cname,
                            code,
                            units,
                            "manual",
                            now_iso,
                            performed_by,
                            "",
                            "delete_all",
                            '{"registered": true}',
                            '{"registered": false}',
                        ),
                    )
            except Exception:
                current_app.logger.exception("failed to write registration_changes_log in delete_registrations")

            cur.execute("DELETE FROM registrations WHERE student_id = ?", (sid,))
            conn.commit()
        return jsonify({"status":"ok","deleted_for": sid})
    except Exception as e:
        current_app.logger.exception("delete_registrations failed")
        return jsonify({"status":"error","message": str(e)}), 500


@students_bp.route("/recompute_conflicts", methods=["POST"])
@role_required("admin")
def recompute_conflicts_route():
    """
    إعادة حساب تعارضات الجدول لجميع الطلبة وملء conflict_report.
    يُستدعى يدوياً من صفحة النتائج أو تلقائياً بعد اعتماد الخطة/تحديث الجدول.
    """
    try:
        with get_connection() as conn:
            count = recompute_conflict_report(conn)
        return jsonify({"status": "ok", "message": f"تم تحديث التعارضات ({count} تعارض)", "count": count}), 200
    except Exception as e:
        current_app.logger.exception("recompute_conflicts failed")
        return jsonify({"status": "error", "message": str(e)}), 500


@students_bp.route("/import_registrations", methods=["POST"])
@login_required
def import_registrations():
    if _is_instructor_or_supervisor_view_only():
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
    data = request.get_json(force=True) or {}
    items = data.get("items", []) or []
    added = 0
    with get_connection() as conn:
        cur = conn.cursor()
        cols = [r[1] for r in cur.execute("PRAGMA table_info(students)").fetchall()]
        has_uni = 'university_number' in cols

        for it in items:
            sid = normalize_sid(it.get("student_id"))
            name = it.get("name") or it.get("student_name") or ""
            uni = it.get("university_number") or ""
            regs = it.get("registrations", []) or it.get("courses", []) or []
            # dedupe registrations list for this imported record
            if regs:
                _seen = set()
                _dedup = []
                for c in regs:
                    if c not in _seen:
                        _seen.add(c)
                        _dedup.append(c)
                regs = _dedup
            if not sid:
                continue
            try:
                if has_uni:
                    cur.execute("INSERT OR IGNORE INTO students (student_id, student_name, university_number) VALUES (?,?,?)", (sid, name, uni))
                else:
                    cur.execute("INSERT OR IGNORE INTO students (student_id, student_name) VALUES (?,?)", (sid, name))
                cur.execute("DELETE FROM registrations WHERE student_id = ?", (sid,))
                for c in regs:
                    cur.execute("INSERT INTO registrations (student_id, course_name) VALUES (?,?)", (sid, c))
                added += 1
            except Exception:
                current_app.logger.exception("import_registrations failed for %s", sid)
        conn.commit()
    return jsonify({"status":"ok","imported": added})

# -----------------------------
# Export registrations
# -----------------------------
@students_bp.route("/export/registrations")
@login_required
def export_registrations_excel():
    if _is_instructor_or_supervisor_view_only():
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cols = [r[1] for r in cur.execute("PRAGMA table_info(students)").fetchall()]
            has_uni = 'university_number' in cols

            # Scope: تقييد تصدير التسجيلات حسب الدور
            allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
            student_filter_sql = ""
            student_filter_params = []
            if allowed_student_ids is not None:
                if not allowed_student_ids:
                    df = pd.DataFrame(columns=["student_id", "student_name", "university_number", "course_name", "course_code", "units"])
                    return excel_response_from_df(df, filename_prefix="registrations")
                placeholders = ",".join("?" for _ in allowed_student_ids)
                student_filter_sql = f"WHERE r.student_id IN ({placeholders})"
                student_filter_params = list(allowed_student_ids)

            # الفصل الحالي لتوثيق التوقيع (يرتبط بالتسجيل الفعلي)
            try:
                term_name, term_year = get_current_term(conn=conn)
                term_label = f"{term_name} {term_year}".strip()
            except Exception:
                term_label = ""

            # تأكد من وجود جدول التوقيعات حتى لا يفشل التصدير على قواعد قديمة
            try:
                _ensure_registration_signature_tables(cur)
            except Exception:
                pass

            sig_join = ""
            sig_params = []
            if term_label:
                sig_join = "LEFT JOIN registration_signatures rs ON rs.student_id = r.student_id AND rs.term = ?"
                sig_params = [term_label]

            if has_uni:
                rows = cur.execute(
                    f"""
                    SELECT r.student_id,
                           COALESCE(s.student_name, '') AS student_name,
                           COALESCE(s.university_number, '') AS university_number,
                           r.course_name,
                           COALESCE(c.course_code, '') AS course_code,
                           COALESCE(c.units, 0) AS units,
                           COALESCE(rs.student_signed, 0) AS student_signed,
                           COALESCE(rs.signed_at, '') AS signed_at,
                           COALESCE(rs.signature_note, '') AS signature_note,
                           COALESCE(rs.form_file_id, 0) AS form_file_id
                    FROM registrations r
                    LEFT JOIN students s ON r.student_id = s.student_id
                    LEFT JOIN courses c ON r.course_name = c.course_name
                    {sig_join}
                    {student_filter_sql}
                    ORDER BY r.student_id, r.course_name
                    """,
                    sig_params + student_filter_params,
                ).fetchall()
            else:
                rows = cur.execute(
                    f"""
                    SELECT r.student_id,
                           COALESCE(s.student_name, '') AS student_name,
                           '' AS university_number,
                           r.course_name,
                           COALESCE(c.course_code, '') AS course_code,
                           COALESCE(c.units, 0) AS units,
                           COALESCE(rs.student_signed, 0) AS student_signed,
                           COALESCE(rs.signed_at, '') AS signed_at,
                           COALESCE(rs.signature_note, '') AS signature_note,
                           COALESCE(rs.form_file_id, 0) AS form_file_id
                    FROM registrations r
                    LEFT JOIN students s ON r.student_id = s.student_id
                    LEFT JOIN courses c ON r.course_name = c.course_name
                    {sig_join}
                    {student_filter_sql}
                    ORDER BY r.student_id, r.course_name
                    """,
                    sig_params + student_filter_params,
                ).fetchall()

        data = []
        for r in rows:
            data.append({
                "student_id": r[0] or "",
                "student_name": r[1] or "",
                "university_number": r[2] or "",
                "course_name": r[3] or "",
                "course_code": r[4] or "",
                "units": int(r[5]) if r[5] is not None else 0,
                "student_signed": "نعم" if int(r[6] or 0) else "لا",
                "signed_at": r[7] or "",
                "signature_note": r[8] or "",
                "has_signed_form_file": "نعم" if int(r[9] or 0) else "لا",
            })
        df = pd.DataFrame(
            data,
            columns=[
                "student_id",
                "student_name",
                "university_number",
                "course_name",
                "course_code",
                "units",
                "student_signed",
                "signed_at",
                "signature_note",
                "has_signed_form_file",
            ],
        )
        return excel_response_from_df(df, filename_prefix="registrations")
    except Exception:
        current_app.logger.exception("export_registrations_excel failed")
        return jsonify({"status":"error","message":"فشل التصدير"}), 500


@students_bp.route("/registration_signature", methods=["GET"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def get_registration_signature():
    sid = normalize_sid(request.args.get("student_id"))
    if not sid:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400
    term = (request.args.get("term") or "").strip()
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            _ensure_registration_signature_tables(cur)
            if not term:
                try:
                    tname, tyear = get_current_term(conn=conn)
                    term = f"{tname} {tyear}".strip()
                except Exception:
                    term = ""
            if not term:
                return jsonify({"student_id": sid, "term": "", "student_signed": False, "signed_at": "", "signature_note": "", "form_file_id": None})
            row = cur.execute(
                """
                SELECT student_signed, COALESCE(signed_at,''), COALESCE(signature_note,''), form_file_id
                FROM registration_signatures
                WHERE student_id = ? AND term = ?
                """,
                (sid, term),
            ).fetchone()
            ev = cur.execute(
                """
                SELECT form_version_id, COALESCE(form_version_no,0)
                FROM registration_signature_events
                WHERE student_id = ? AND term = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (sid, term),
            ).fetchone()
            if not row:
                return jsonify({"student_id": sid, "term": term, "student_signed": False, "signed_at": "", "signature_note": "", "form_file_id": None, "form_version_id": (int(ev[0]) if ev and ev[0] else None), "form_version_no": (int(ev[1]) if ev and ev[1] else 0)})
            return jsonify(
                {
                    "student_id": sid,
                    "term": term,
                    "student_signed": bool(int(row[0] or 0)),
                    "signed_at": row[1] or "",
                    "signature_note": row[2] or "",
                    "form_file_id": (int(row[3]) if row[3] else None),
                    "form_version_id": (int(ev[0]) if ev and ev[0] else None),
                    "form_version_no": (int(ev[1]) if ev and ev[1] else 0),
                }
            )
    except Exception:
        current_app.logger.exception("get_registration_signature failed")
        return jsonify({"status": "error", "message": "فشل جلب التوقيع"}), 500


@students_bp.route("/registration_signature/upload", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def upload_registration_signature_file():
    sid = normalize_sid(request.form.get("student_id"))
    if not sid:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400
    term = (request.form.get("term") or "").strip()
    f = request.files.get("file")
    if not f:
        return jsonify({"status": "error", "message": "file مطلوب"}), 400

    if not term:
        try:
            with get_connection() as conn:
                tname, tyear = get_current_term(conn=conn)
                term = f"{tname} {tyear}".strip()
        except Exception:
            term = ""
    if not term:
        return jsonify({"status": "error", "message": "تعذر تحديد الفصل الحالي"}), 400

    filename = (f.filename or "").strip()
    ext = os.path.splitext(filename)[1].lower()
    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
    if ext not in allowed:
        return jsonify({"status": "error", "message": "صيغة غير مسموحة. المسموح: PDF/PNG/JPG/WEBP"}), 400

    raw = f.read()
    if not raw:
        return jsonify({"status": "error", "message": "ملف فارغ"}), 400
    if len(raw) > 10 * 1024 * 1024:
        return jsonify({"status": "error", "message": "حجم الملف كبير (الحد 10MB)"}), 400

    sha = hashlib.sha256(raw).hexdigest()
    safe_term = "".join([c for c in term if c.isalnum() or c in (" ", "-", "_")]).strip().replace(" ", "_") or "term"
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads", "registration_forms"))
    os.makedirs(base_dir, exist_ok=True)
    stored_name = f"{sid}__{safe_term}__{sha[:12]}{ext}"
    stored_path = os.path.join(base_dir, stored_name)
    try:
        with open(stored_path, "wb") as out:
            out.write(raw)
    except Exception:
        current_app.logger.exception("failed to write signature file")
        return jsonify({"status": "error", "message": "فشل حفظ الملف"}), 500

    try:
        with get_connection() as conn:
            cur = conn.cursor()
            _ensure_registration_signature_tables(cur)
            uploaded_by = (session.get("user") or "") if "user" in session else ""
            mime = (f.mimetype or "").strip()
            cur.execute(
                """
                INSERT INTO registration_form_files
                (student_id, term, original_name, stored_path, mime_type, file_size, sha256, uploaded_by, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sid,
                    term,
                    filename,
                    stored_path,
                    mime,
                    len(raw),
                    sha,
                    uploaded_by,
                    datetime.datetime.utcnow().isoformat(),
                ),
            )
            file_id = cur.lastrowid
            conn.commit()
        return jsonify({"status": "ok", "file_id": file_id, "download_url": f"/students/registration_signature/file/{file_id}"})
    except Exception:
        current_app.logger.exception("upload_registration_signature_file failed")
        return jsonify({"status": "error", "message": "فشل تسجيل الملف في قاعدة البيانات"}), 500


@students_bp.route("/registration_signature/file/<int:file_id>", methods=["GET"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def download_registration_signature_file(file_id: int):
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            _ensure_registration_signature_tables(cur)
            row = cur.execute(
                "SELECT original_name, stored_path, mime_type FROM registration_form_files WHERE id = ?",
                (int(file_id),),
            ).fetchone()
            if not row:
                return jsonify({"status": "error", "message": "الملف غير موجود"}), 404
            original_name, stored_path, mime_type = row[0] or "signed_form", row[1] or "", row[2] or ""
        if not stored_path or not os.path.isfile(stored_path):
            return jsonify({"status": "error", "message": "مسار الملف غير موجود على القرص"}), 404
        return send_file(
            stored_path,
            mimetype=(mime_type or "application/octet-stream"),
            as_attachment=True,
            download_name=original_name,
        )
    except Exception:
        current_app.logger.exception("download_registration_signature_file failed")
        return jsonify({"status": "error", "message": "فشل تحميل الملف"}), 500


@students_bp.route("/registration_signatures/list", methods=["GET"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def registration_signatures_list():
    """
    إرجاع توثيقات التوقيع للفصل الحالي (أو فصل محدد):
    - term (اختياري)
    - signed_only=1 (اختياري)
    """
    term = (request.args.get("term") or "").strip()
    signed_only = str(request.args.get("signed_only") or "").lower() in ("1", "true", "yes")
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            _ensure_registration_signature_tables(cur)

            if not term:
                try:
                    tname, tyear = get_current_term(conn=conn)
                    term = f"{tname} {tyear}".strip()
                except Exception:
                    term = ""

            if not term:
                return jsonify({"term": "", "items": []})

            allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
            where = ["rs.term = ?"]
            params = [term]
            if signed_only:
                where.append("COALESCE(rs.student_signed,0) = 1")
            if allowed_student_ids is not None:
                if not allowed_student_ids:
                    return jsonify({"term": term, "items": []})
                placeholders = ",".join("?" for _ in allowed_student_ids)
                where.append(f"rs.student_id IN ({placeholders})")
                params.extend(list(allowed_student_ids))

            q = f"""
            SELECT rs.student_id,
                   COALESCE(s.student_name,'') AS student_name,
                   COALESCE(s.university_number,'') AS university_number,
                   COALESCE(rs.student_signed,0) AS student_signed,
                   COALESCE(rs.signed_at,'') AS signed_at,
                   COALESCE(rs.signature_note,'') AS signature_note,
                   COALESCE(rs.form_file_id,0) AS form_file_id,
                   (
                     SELECT COALESCE(e.form_version_no,0)
                     FROM registration_signature_events e
                     WHERE e.student_id = rs.student_id AND e.term = rs.term
                     ORDER BY e.updated_at DESC, e.id DESC
                     LIMIT 1
                   ) AS form_version_no
            FROM registration_signatures rs
            LEFT JOIN students s ON s.student_id = rs.student_id
            WHERE {' AND '.join(where)}
            ORDER BY rs.student_id
            """
            rows = cur.execute(q, params).fetchall()
            items = []
            for r in rows:
                items.append(
                    {
                        "student_id": r[0] or "",
                        "student_name": r[1] or "",
                        "university_number": r[2] or "",
                        "student_signed": bool(int(r[3] or 0)),
                        "signed_at": r[4] or "",
                        "signature_note": r[5] or "",
                        "form_file_id": (int(r[6]) if r[6] else None),
                        "form_version_no": int(r[7] or 0),
                    }
                )
            return jsonify({"term": term, "items": items})
    except Exception:
        current_app.logger.exception("registration_signatures_list failed")
        return jsonify({"status": "error", "message": "فشل تحميل قائمة التوقيعات"}), 500


@students_bp.route("/export/registration_signatures", methods=["GET"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def export_registration_signatures():
    """
    تصدير قائمة الطلبة الموقعين (أو الجميع) للفصل الحالي إلى Excel.
    query:
      - term (اختياري)
      - signed_only=1 (افتراضي: 1)
    """
    term = (request.args.get("term") or "").strip()
    signed_only = str(request.args.get("signed_only") or "1").lower() in ("1", "true", "yes")
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            _ensure_registration_signature_tables(cur)
            if not term:
                try:
                    tname, tyear = get_current_term(conn=conn)
                    term = f"{tname} {tyear}".strip()
                except Exception:
                    term = ""

            if not term:
                df = pd.DataFrame(columns=["term", "student_id", "student_name", "university_number", "student_signed", "signed_at", "signature_note", "has_form_file"])
                return excel_response_from_df(df, filename_prefix="registration_signatures")

            allowed_student_ids = _get_allowed_student_ids_for_role(conn, session.get("user_role"))
            where = ["rs.term = ?"]
            params = [term]
            if signed_only:
                where.append("COALESCE(rs.student_signed,0) = 1")
            if allowed_student_ids is not None:
                if not allowed_student_ids:
                    df = pd.DataFrame(columns=["term", "student_id", "student_name", "university_number", "student_signed", "signed_at", "signature_note", "has_form_file"])
                    return excel_response_from_df(df, filename_prefix="registration_signatures")
                placeholders = ",".join("?" for _ in allowed_student_ids)
                where.append(f"rs.student_id IN ({placeholders})")
                params.extend(list(allowed_student_ids))

            q = f"""
            SELECT rs.term,
                   rs.student_id,
                   COALESCE(s.student_name,'') AS student_name,
                   COALESCE(s.university_number,'') AS university_number,
                   COALESCE(rs.student_signed,0) AS student_signed,
                   COALESCE(rs.signed_at,'') AS signed_at,
                   COALESCE(rs.signature_note,'') AS signature_note,
                   COALESCE(rs.form_file_id,0) AS form_file_id,
                   (
                     SELECT COALESCE(e.form_version_no,0)
                     FROM registration_signature_events e
                     WHERE e.student_id = rs.student_id AND e.term = rs.term
                     ORDER BY e.updated_at DESC, e.id DESC
                     LIMIT 1
                   ) AS form_version_no
            FROM registration_signatures rs
            LEFT JOIN students s ON s.student_id = rs.student_id
            WHERE {' AND '.join(where)}
            ORDER BY rs.student_id
            """
            rows = cur.execute(q, params).fetchall()

        data = []
        for r in rows:
            data.append(
                {
                    "term": r[0] or "",
                    "student_id": r[1] or "",
                    "student_name": r[2] or "",
                    "university_number": r[3] or "",
                    "student_signed": "نعم" if int(r[4] or 0) else "لا",
                    "signed_at": r[5] or "",
                    "signature_note": r[6] or "",
                    "has_form_file": "نعم" if int(r[7] or 0) else "لا",
                    "form_version_no": int(r[8] or 0),
                }
            )
        df = pd.DataFrame(
            data,
            columns=["term", "student_id", "student_name", "university_number", "student_signed", "signed_at", "signature_note", "has_form_file", "form_version_no"],
        )
        return excel_response_from_df(df, filename_prefix="registration_signatures")
    except Exception:
        current_app.logger.exception("export_registration_signatures failed")
        return jsonify({"status": "error", "message": "فشل تصدير قائمة التوقيعات"}), 500


@students_bp.route("/export/attendance")
@login_required
def export_attendance_excel():
    """
    تصدير سجلات الحضور/الغياب في ملف Excel متعدد الأوراق.
    يسمح بتحديد مقررات متعددة (?course=اسم1&course=اسم2) وتحديد عدد الأسابيع (?weeks=10).
    """
    try:
        r = _collect_attendance_export_state(get_connection, get_current_term, normalize_sid, course_name_lock=None)
        if r["kind"] == "http":
            return r["response"]
        if r["kind"] == "empty_excel":
            frames = [("ملخص", pd.DataFrame(r["summaries"]))]
            return excel_response_from_frames(frames, filename_prefix="attendance")

        weeks = r["weeks"]
        selected_courses = r["selected_courses"]
        course_students = r["course_students"]
        attendance_map = r["attendance_map"]
        missing_courses = r["missing_courses"]

        summaries = []
        frames = []
        week_columns = [f"الأسبوع {i}" for i in range(1, weeks + 1)]

        for course_name in selected_courses:
            students_list = course_students.get(course_name, [])
            notes = ""
            if not students_list:
                notes = "لا توجد تسجيلات للمقرر"
            summaries.append({
                "المقرر": course_name,
                "عدد الطلبة": len(students_list),
                "عدد الأسابيع": weeks,
                "ملاحظات": notes
            })

            rows = []
            for student in students_list:
                sid = student["student_id"]
                row = {
                    "الرقم الدراسي": sid,
                    "اسم الطالب": student["student_name"]
                }
                week_statuses = attendance_map.get((course_name, sid), {})
                for idx, col in enumerate(week_columns, start=1):
                    row[col] = week_statuses.get(idx, "")
                rows.append(row)

            if rows:
                df = pd.DataFrame(rows)
            else:
                df = pd.DataFrame(columns=["الرقم الدراسي", "اسم الطالب", *week_columns])
            frames.append((course_name, df))

        seen_missing = set()
        for missing in missing_courses:
            mk = missing.lower()
            if mk in seen_missing:
                continue
            seen_missing.add(mk)
            summaries.append({
                "المقرر": missing,
                "عدد الطلبة": 0,
                "عدد الأسابيع": weeks,
                "ملاحظات": "المقرر غير موجود في قاعدة البيانات"
            })

        summary_df = pd.DataFrame(summaries)
        frames.insert(0, ("ملخص", summary_df))

        return excel_response_from_frames(frames, filename_prefix="attendance")
    except Exception:
        current_app.logger.exception("export_attendance_excel failed")
        return jsonify({"status": "error", "message": "فشل تصدير الحضور"}), 500


def _attendance_status_label_ar(code: str) -> str:
    c = (code or "").strip().lower()
    if c == "present":
        return "حضور"
    if c == "absent":
        return "غياب"
    if c == "late":
        return "تأخر"
    if c == "excused":
        return "معذور"
    return code or "—"


def _normalize_attendance_print_orientation() -> str:
    o = (request.args.get("orientation") or "landscape").strip().lower()
    return o if o in ("portrait", "landscape") else "landscape"


def _attendance_print_context(course: str, *, print_orientation: str | None = None):
    """يُرجع (None, dict للقالب) أو (tuple استجابة خطأ, None)."""
    if print_orientation is None:
        print_orientation = _normalize_attendance_print_orientation()
    elif print_orientation not in ("portrait", "landscape"):
        print_orientation = "landscape"
    course = (course or "").strip()
    if not course:
        return (jsonify({"status": "error", "message": "حدد اسم المقرر"}), 400), None

    r = _collect_attendance_export_state(
        get_connection, get_current_term, normalize_sid, course_name_lock=course
    )
    if r["kind"] == "http":
        return r["response"], None
    if r["kind"] == "empty_excel":
        return jsonify({"status": "error", "message": "لا توجد مقررات مسموحة أو بيانات للمقرر"}), 404
    if len(r["selected_courses"]) != 1:
        return jsonify({"status": "error", "message": "المقرر غير متاح أو غير مسموح لحسابك"}), 403

    cn = r["selected_courses"][0]
    weeks = r["weeks"]
    students_list = r["course_students"].get(cn, [])
    attendance_map = r["attendance_map"]
    semester_label = r["semester_label"] or ""

    course_code = ""
    instructor_name = ""
    with get_connection() as conn:
        cur = conn.cursor()
        crow = cur.execute(
            "SELECT COALESCE(course_code,'') FROM courses WHERE course_name = ? LIMIT 1",
            (cn,),
        ).fetchone()
        if crow:
            course_code = crow[0] or ""
        if semester_label:
            irow = cur.execute(
                """
                SELECT COALESCE(instructor,'') FROM schedule
                WHERE course_name = ? AND semester = ? LIMIT 1
                """,
                (cn, semester_label),
            ).fetchone()
            if irow:
                instructor_name = irow[0] or ""

    table_rows = []
    for student in students_list:
        sid = student["student_id"]
        week_statuses = attendance_map.get((cn, sid), {})
        cells = []
        for w in range(1, weeks + 1):
            raw = week_statuses.get(w, "")
            cells.append(_attendance_status_label_ar(str(raw)))
        table_rows.append({
            "student_id": sid,
            "student_name": student["student_name"] or "",
            "weeks": cells,
        })

    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ctx = {
        "course_name": cn,
        "course_code": course_code,
        "semester_label": semester_label,
        "instructor_name": instructor_name,
        "weeks": weeks,
        "week_numbers": list(range(1, weeks + 1)),
        "table_rows": table_rows,
        "student_count": len(students_list),
        "generated_at": generated_at,
        "print_orientation": print_orientation,
    }
    return None, ctx


@students_bp.route("/export/attendance/print")
@login_required
def export_attendance_print():
    """معاينة رسمية للطباعة (مقرر واحد)."""
    try:
        err, ctx = _attendance_print_context(
            request.args.get("course") or "",
            print_orientation=_normalize_attendance_print_orientation(),
        )
        if err is not None:
            return err
        return render_template("attendance_sheet_print.html", **ctx)
    except Exception:
        current_app.logger.exception("export_attendance_print failed")
        return jsonify({"status": "error", "message": "فشل إنشاء صفحة الطباعة"}), 500


@students_bp.route("/export/attendance/pdf")
@login_required
def export_attendance_pdf():
    """تصدير PDF لمقرر واحد."""
    try:
        err, ctx = _attendance_print_context(
            request.args.get("course") or "",
            print_orientation=_normalize_attendance_print_orientation(),
        )
        if err is not None:
            return err
        html = render_template("attendance_sheet_print.html", **ctx)
        safe_name = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in ctx["course_name"])[:60]
        return pdf_response_from_html(html, filename_prefix=f"attendance_{safe_name}")
    except Exception:
        current_app.logger.exception("export_attendance_pdf failed")
        return jsonify({"status": "error", "message": "فشل تجهيز PDF"}), 500


@students_bp.route("/attendance_allowed_courses")
@login_required
def attendance_allowed_courses():
    """
    قائمة مقررات الحضور: مبنية على التسجيلات الفعلية (registrations) للفصل الحالي،
    مربوطة بصف الجدول schedule بنفس الفصل مع تطبيع اسم المقرر (ليس مساواة حرفية صارمة).
    """
    user_role = session.get("user_role") or ""
    if not user_role:
        return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

    # الإدارة: مقررات لها تسجيل فعلي للفصل الحالي، مربوطة بالجدول بعد تطبيع اسم المقرر (كما في التصدير)
    if user_role in ("admin", "admin_main", "head_of_department"):
        with get_connection() as conn:
            cur = conn.cursor()
            term_name, term_year = get_current_term(conn=conn)
            semester_label = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()
            if not semester_label:
                return jsonify(
                    {"status": "error", "message": "لا يمكن تحديد الفصل الحالي", "code": "FORBIDDEN"}
                ), 403
            sem_sql, sem_bind = build_schedule_semester_match("s.semester", term_name, term_year)
            sched_sem_and = f" AND (({sem_sql}) OR TRIM(COALESCE(s.semester, '')) = '')"
            rows = cur.execute(
                f"""
                SELECT DISTINCT r.course_name,
                       COALESCE(c.course_code,'') AS course_code,
                       COALESCE(c.units,0) AS units
                FROM registrations r
                INNER JOIN students st ON st.student_id = r.student_id
                    AND COALESCE(st.enrollment_status, 'active') = 'active'
                INNER JOIN schedule s
                  ON LOWER(TRIM(COALESCE(r.course_name, ''))) = LOWER(TRIM(COALESCE(s.course_name, '')))
                {sched_sem_and}
                LEFT JOIN courses c
                  ON LOWER(TRIM(COALESCE(r.course_name, ''))) = LOWER(TRIM(COALESCE(c.course_name, '')))
                WHERE COALESCE(r.course_name, '') <> ''
                ORDER BY r.course_name
                """,
                tuple(sem_bind),
            ).fetchall()
            if not rows:
                fb = fallback_distinct_attendance_courses(cur, term_name, term_year)
                rows = course_rows_with_meta(cur, fb)
        courses = [
            {"course_name": r[0], "course_code": r[1], "units": int(r[2] or 0)}
            for r in rows
            if r and r[0]
        ]
        return jsonify({"status": "ok", "courses": courses})

    effective_supervisor = user_role == "supervisor" or (
        user_role == "instructor" and int(session.get("is_supervisor") or 0) == 1
    )

    with get_connection() as conn:
        cur = conn.cursor()
        term_name, term_year = get_current_term(conn=conn)
        semester_label = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()
        if not semester_label:
            return jsonify({"status": "error", "message": "لا يمكن تحديد الفصل الحالي", "code": "FORBIDDEN"}), 403

        sem_sql, sem_bind = build_schedule_semester_match("s.semester", term_name, term_year)
        sched_sem_and = f" AND (({sem_sql}) OR TRIM(COALESCE(s.semester, '')) = '')"

        if effective_supervisor:
            instructor_id = session.get("instructor_id")
            if not instructor_id:
                return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

            rows = cur.execute(
                f"""
                SELECT DISTINCT r.course_name,
                                COALESCE(c.course_code,'') AS course_code,
                                COALESCE(c.units,0) AS units
                FROM registrations r
                INNER JOIN students st ON st.student_id = r.student_id
                    AND COALESCE(st.enrollment_status, 'active') = 'active'
                INNER JOIN schedule s
                  ON LOWER(TRIM(COALESCE(r.course_name, ''))) = LOWER(TRIM(COALESCE(s.course_name, '')))
                {sched_sem_and}
                LEFT JOIN courses c
                  ON LOWER(TRIM(COALESCE(r.course_name, ''))) = LOWER(TRIM(COALESCE(c.course_name, '')))
                WHERE r.student_id IN (
                      SELECT student_id FROM student_supervisor WHERE instructor_id = ?
                  )
                  AND COALESCE(r.course_name, '') <> ''
                ORDER BY r.course_name
                """,
                tuple(sem_bind) + (instructor_id,),
            ).fetchall()
            if not rows:
                fb = fallback_distinct_attendance_courses(
                    cur, term_name, term_year, supervisor_instructor_id=int(instructor_id)
                )
                rows = course_rows_with_meta(cur, fb)

        elif user_role == "instructor":
            instructor_id = session.get("instructor_id")
            if not instructor_id:
                return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

            instr_row = cur.execute(
                "SELECT name FROM instructors WHERE id = ? LIMIT 1",
                (instructor_id,),
            ).fetchone()
            if not instr_row:
                return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

            instructor_name = instr_row[0]
            rows = cur.execute(
                f"""
                SELECT DISTINCT r.course_name,
                                COALESCE(c.course_code,'') AS course_code,
                                COALESCE(c.units,0) AS units
                FROM registrations r
                INNER JOIN students st ON st.student_id = r.student_id
                    AND COALESCE(st.enrollment_status, 'active') = 'active'
                INNER JOIN schedule s
                  ON LOWER(TRIM(COALESCE(r.course_name, ''))) = LOWER(TRIM(COALESCE(s.course_name, '')))
                {sched_sem_and}
                 AND TRIM(COALESCE(s.instructor, '')) = TRIM(?)
                LEFT JOIN courses c
                  ON LOWER(TRIM(COALESCE(r.course_name, ''))) = LOWER(TRIM(COALESCE(c.course_name, '')))
                WHERE COALESCE(r.course_name, '') <> ''
                ORDER BY r.course_name
                """,
                tuple(sem_bind) + (instructor_name,),
            ).fetchall()
            if not rows:
                fb = fallback_distinct_attendance_courses(
                    cur, term_name, term_year, instructor_name=instructor_name
                )
                rows = course_rows_with_meta(cur, fb)

        else:
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403

    courses = [
        {"course_name": r[0], "course_code": r[1], "units": int(r[2] or 0)}
        for r in rows
        if r and r[0]
    ]
    return jsonify({"status": "ok", "courses": courses})


# -----------------------------
# Eligible courses for registration
# -----------------------------
@students_bp.route("/eligible_courses")
@login_required
def eligible_courses():
    """
    المقررات المتاحة للطالب ضمن خطته الدراسية: فقط المقررات الموجودة في الجدول الدراسي المعتمد.
    إذا لم يُنشر الجدول بعد، تُرجع eligible فارغة و schedule_published=False.
    """
    sid = normalize_sid(request.args.get("student_id"))
    if not sid:
        return jsonify({"eligible": [], "completed": [], "schedule_published": False})

    PASS_TEXT = {'p','pass','نجاح','مقبول','a','b','c'}
    PASS_NUM_THRESHOLD = 50.0

    try:
        with get_connection() as conn:
            cur = conn.cursor()
            published_at = get_schedule_published_at(conn)
            if published_at is None:
                try:
                    grade_rows = cur.execute(
                        "SELECT course_name, grade FROM grades WHERE student_id = ?", (sid,)
                    ).fetchall()
                except Exception:
                    grade_rows = []
                grade_map = {r[0]: r[1] for r in grade_rows}
                try:
                    all_rows = cur.execute(
                        "SELECT course_name, COALESCE(course_code, ''), COALESCE(units, 0) FROM courses"
                    ).fetchall()
                    all_courses = [{"course_name": r[0], "course_code": r[1], "units": r[2]} for r in all_rows]
                except Exception:
                    all_courses = []
                completed = []
                for c in all_courses:
                    g = grade_map.get(c["course_name"], None)
                    if g is None:
                        continue
                    passed = False
                    try:
                        if float(g) >= PASS_NUM_THRESHOLD:
                            passed = True
                    except Exception:
                        pass
                    if not passed and isinstance(g, str) and g.strip().lower() in PASS_TEXT:
                        passed = True
                    if passed:
                        completed.append({**c, "grade": g})
                return jsonify({"eligible": [], "completed": completed, "schedule_published": False})

            schedule_course_names = {
                str(r[0]).strip()
                for r in cur.execute(
                    "SELECT DISTINCT course_name FROM schedule WHERE COALESCE(course_name,'') <> ''"
                ).fetchall()
                if str(r[0] or "").strip()
            }
            try:
                all_rows = cur.execute(
                    "SELECT course_name, COALESCE(course_code, ''), COALESCE(units, 0) FROM courses"
                ).fetchall()
                all_courses = [
                    {"course_name": str(r[0]).strip(), "course_code": r[1], "units": r[2]}
                    for r in all_rows
                    if str(r[0] or "").strip()
                ]
            except Exception:
                all_rows = cur.execute("SELECT DISTINCT course_name FROM schedule").fetchall()
                all_courses = [
                    {"course_name": str(r[0]).strip(), "course_code": "", "units": 0}
                    for r in all_rows
                    if str(r[0] or "").strip()
                ]

            # مقررات وردت في الجدول الدراسي دون صف مطابق في courses (أو اختلاف مسافات)
            by_name = {c["course_name"]: c for c in all_courses}
            for scn in schedule_course_names:
                if scn not in by_name:
                    by_name[scn] = {"course_name": scn, "course_code": "", "units": 0}
            all_courses = [by_name[k] for k in sorted(by_name.keys()) if k in schedule_course_names]

            grade_rows = cur.execute(
                "SELECT course_name, grade FROM grades WHERE student_id = ? ORDER BY course_name",
                (sid,),
            ).fetchall()
            grade_map = {}
            for r in grade_rows:
                cn = str(r[0] or "").strip()
                if cn:
                    grade_map[cn] = r[1]

            eligible = []
            completed = []
            for c in all_courses:
                cname = c["course_name"]
                g = grade_map.get(cname, None)
                if g is None:
                    eligible.append(c)
                    continue
                passed = False
                try:
                    gn = float(g)
                    if gn >= PASS_NUM_THRESHOLD:
                        passed = True
                except Exception:
                    pass
                if not passed:
                    if isinstance(g, str) and g.strip().lower() in PASS_TEXT:
                        passed = True
                if passed:
                    comp = c.copy()
                    comp["grade"] = g
                    completed.append(comp)
                else:
                    eligible.append(c)

        return jsonify({"eligible": eligible, "completed": completed, "schedule_published": True})
    except Exception:
        current_app.logger.exception("eligible_courses failed")
        return jsonify({"eligible": [], "completed": [], "schedule_published": False})

# -----------------------------
# Timetable conflicts (robust)
# -----------------------------
def parse_time_range(value):
    """
    Accept formats:
      - "08:00-10:00"
      - "08:00 - 10:00"
      - "08:00" (treated as start only)
      - "08:00/10:00" etc.
    Return tuple (start, end) where end may be '' if not available.
    """
    if not value:
        return ("", "")
    v = str(value).strip()
    # try common delimiters
    for sep in ['-', '–', '—', '/', '\\', ' to ']:
        if sep in v:
            parts = [p.strip() for p in v.split(sep) if p.strip()]
            if len(parts) >= 2:
                return (parts[0], parts[1])
    # single time
    return (v, '')

@students_bp.route("/timetable/conflicts")
@login_required
def timetable_conflicts():
    """
    Return conflicts grouped by (day, start, end, room).
    Tries to detect time columns named: start_time,end_time OR time OR timeslot OR time_range.
    If times are combined (e.g. "08:00-10:00") parse them.
    """
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # --- First choice: use conflict_report (source of truth) ---
            # This prevents false positives caused by timetable/schedule tables
            # having different time formats or missing student identifiers.
            try:
                has_cr = cur.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='conflict_report'",
                ).fetchone()
                if has_cr:
                    rows = cur.execute(
                        """
                        SELECT
                            COALESCE(student_id,'') AS student_id,
                            COALESCE(day,'') AS day,
                            COALESCE(time,'') AS time,
                            COALESCE(conflicting_sections,'') AS conflicting_sections
                        FROM conflict_report
                        """
                    ).fetchall()
                    if not rows:
                        return jsonify({"conflicts": []})

                    # parse names for student_ids present
                    student_ids = sorted({(r["student_id"] or "").strip() for r in rows if (r["student_id"] or "").strip()})
                    name_map = {}
                    if student_ids:
                        try:
                            q2 = "SELECT student_id, COALESCE(student_name,'') as student_name FROM students WHERE student_id IN ({})".format(
                                ",".join("?" for _ in student_ids)
                            )
                            rows2 = cur.execute(q2, student_ids).fetchall()
                            name_map = {r["student_id"]: r["student_name"] for r in rows2}
                        except Exception:
                            name_map = {}

                    slots = {}
                    for r in rows:
                        sid = (r["student_id"] or "").strip()
                        day = (r["day"] or "").strip()
                        ts = (r["time"] or "").strip()
                        start, end = parse_time_range(ts)
                        # If parse failed, avoid returning empty start/end (frontend should not match '' reliably)
                        start = start or ""
                        end = end or ""
                        room = ""
                        key = f"{day}|{start}|{end}|{room}"
                        if key not in slots:
                            slots[key] = {
                                "day": day,
                                "start_time": start,
                                "end_time": end,
                                "room": room,
                                "entries": [],
                            }
                        slots[key]["entries"].append({
                            "student_id": sid,
                            "student_name": name_map.get(sid, ""),
                            "course_name": r["conflicting_sections"] or "",
                            "section": "",
                            "note": "",
                        })

                    conflicts = []
                    for s in slots.values():
                        if s["entries"]:
                            conflicts.append(s)
                    return jsonify({"conflicts": conflicts})
            except Exception:
                # fallback to legacy logic below
                current_app.logger.exception("timetable/conflicts: conflict_report path failed")

            # --- Fallback: legacy robust parsing (may produce false positives) ---
            # detect table
            # (kept to avoid breaking older installations)

            # detect table
            tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            table_name = None
            for t in ("timetable", "schedule", "sessions"):
                if t in tables:
                    table_name = t
                    break
            if not table_name:
                table_name = tables[0] if tables else "timetable"

            # inspect columns
            cols_info = cur.execute(f"PRAGMA table_info({table_name})").fetchall()
            col_names = [c[1] for c in cols_info]

            # determine which time columns exist
            has_start = 'start_time' in col_names and 'end_time' in col_names
            has_time_single = 'time' in col_names or 'time_range' in col_names or 'timeslot' in col_names
            # build query selecting flexible columns (use COALESCE and aliases)
            select_cols = []
            # day
            if 'day' in col_names:
                select_cols.append("COALESCE(day, '') AS day")
            else:
                select_cols.append("COALESCE(weekday, '') AS day")
            # start/end or single time
            if has_start:
                select_cols.append("COALESCE(start_time, '') AS start_time")
                select_cols.append("COALESCE(end_time, '') AS end_time")
            elif 'time' in col_names:
                select_cols.append("COALESCE(time, '') AS time_single")
            elif 'time_range' in col_names:
                select_cols.append("COALESCE(time_range, '') AS time_single")
            elif 'timeslot' in col_names:
                select_cols.append("COALESCE(timeslot, '') AS time_single")
            else:
                # no time-related column detected — attempt to select a few common names
                select_cols.append("COALESCE(time, '') AS time_single")

            # other common columns
            for cname in ("room", "course_name", "student_id", "section", "note"):
                if cname in col_names:
                    select_cols.append(f"COALESCE({cname}, '') AS {cname}")
                else:
                    select_cols.append(f"'' AS {cname}")

            q = f"SELECT {', '.join(select_cols)} FROM {table_name}"
            try:
                rows = cur.execute(q).fetchall()
            except Exception:
                current_app.logger.exception("timetable/conflicts: query failed (check table/columns)")
                return jsonify({"conflicts": []})

            slots = {}
            for r in rows:
                rowd = dict(r)
                day = rowd.get("day", "") or ""
                # parse start/end depending on which columns present
                if "start_time" in rowd and "end_time" in rowd:
                    start = rowd.get("start_time","") or ""
                    end = rowd.get("end_time","") or ""
                else:
                    ts = rowd.get("time_single","") or ""
                    start, end = parse_time_range(ts)
                room = rowd.get("room","") or ""
                course = rowd.get("course_name","") or ""
                sid = rowd.get("student_id","") or ""
                section = rowd.get("section","") or ""
                note = rowd.get("note","") or ""

                key = f"{day}|{start}|{end}|{room}"
                slots.setdefault(key, {"day": day, "start_time": start, "end_time": end, "room": room, "entries": []})
                slots[key]["entries"].append({
                    "student_id": sid,
                    "student_name": "",
                    "course_name": course,
                    "section": section,
                    "note": note
                })

            # fetch student names for present student_ids
            student_ids = sorted({e["student_id"] for s in slots.values() for e in s["entries"] if e["student_id"]})
            name_map = {}
            if student_ids:
                try:
                    q2 = "SELECT student_id, COALESCE(student_name,'') as student_name FROM students WHERE student_id IN ({})".format(",".join("?" for _ in student_ids))
                    rows2 = cur.execute(q2, student_ids).fetchall()
                    name_map = {r["student_id"]: r["student_name"] for r in rows2}
                except Exception:
                    current_app.logger.exception("timetable/conflicts: failed fetching student names")

            conflicts = []
            for k, s in slots.items():
                entries = s["entries"]
                unique_students = {e["student_id"] for e in entries if e["student_id"]}
                unique_course_sections = {(e["course_name"], e.get("section","")) for e in entries}
                if len(entries) > 1 and (len(unique_students) > 1 or len(unique_course_sections) > 1):
                    for e in entries:
                        sid = e.get("student_id") or ""
                        e["student_name"] = name_map.get(sid, "")
                    s["key"] = k
                    conflicts.append(s)

            return jsonify({"conflicts": conflicts})
    except Exception:
        current_app.logger.exception("timetable_conflicts failed outer")
        return jsonify({"conflicts": []})

# -----------------------------
# استيراد / تصدير بيانات الطلاب (موجودة سابقاً)
# -----------------------------
@students_bp.route("/export/excel")
@login_required
def students_export_excel():
    try:
        user_role = session.get("user_role")
        with get_connection() as conn:
            allowed_student_ids = _get_allowed_student_ids_for_role(conn, user_role)

        if allowed_student_ids is not None and not allowed_student_ids:
            return excel_response_from_df(
                pd.DataFrame(columns=[
                    "الرقم الدراسي",
                    "اسم الطالب",
                    "فصل الالتحاق",
                    "سنة الالتحاق",
                    "خطة التخرج",
                    "حالة القيد",
                    "فصل وسنة الإجراء",
                    "ملاحظة القيد",
                    "تاريخ آخر تغيير للحالة",
                ]),
                filename_prefix="students",
            )

        students = students_filtered_from_request(request)
        if allowed_student_ids is not None:
            students = [s for s in students if normalize_sid(s.get("student_id")) in allowed_student_ids]
        rows_out = []
        for s in students:
            rows_out.append(
                {
                    "الرقم الدراسي": s.get("student_id"),
                    "اسم الطالب": s.get("student_name") or "",
                    "فصل الالتحاق": (s.get("join_term") or "").strip(),
                    "سنة الالتحاق": (s.get("join_year") or "").strip(),
                    "خطة التخرج": (s.get("graduation_plan") or "").strip(),
                    "حالة القيد": _enrollment_label_ar(s.get("enrollment_status")),
                    "فصل وسنة الإجراء": _format_status_action_period(
                        s.get("status_changed_term"), s.get("status_changed_year")
                    )
                    or "—",
                    "ملاحظة القيد": (s.get("status_reason") or "").strip(),
                    "تاريخ آخر تغيير للحالة": (s.get("status_changed_at") or "") or "—",
                }
            )
        _cols = [
            "الرقم الدراسي",
            "اسم الطالب",
            "فصل الالتحاق",
            "سنة الالتحاق",
            "خطة التخرج",
            "حالة القيد",
            "فصل وسنة الإجراء",
            "ملاحظة القيد",
            "تاريخ آخر تغيير للحالة",
        ]
        df = pd.DataFrame(rows_out, columns=_cols) if rows_out else pd.DataFrame(columns=_cols)
        return excel_response_from_df(df, filename_prefix="students")
    except Exception:
        current_app.logger.exception("students_export_excel failed")
        return jsonify({"status": "error", "message": "فشل التصدير"}), 500

@students_bp.route("/export/pdf")
@login_required
def students_export_pdf():
    try:
        user_role = session.get("user_role")
        with get_connection() as conn:
            allowed_student_ids = _get_allowed_student_ids_for_role(conn, user_role)

        if allowed_student_ids is not None and not allowed_student_ids:
            generated_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            summary = students_filter_summary_ar(request)
            html = render_template(
                "export_students.html",
                students=[],
                rows=[],
                filter_summary=summary,
                generated_at=generated_at,
            )
            return pdf_response_from_html(html, filename_prefix="students")

        students = students_filtered_from_request(request)
        if allowed_student_ids is not None:
            students = [s for s in students if normalize_sid(s.get("student_id")) in allowed_student_ids]
        rows = []
        for s in students:
            rows.append(
                {
                    "student_id": s.get("student_id"),
                    "student_name": s.get("student_name") or "",
                    "join_term": (s.get("join_term") or "").strip(),
                    "join_year": (s.get("join_year") or "").strip(),
                    "graduation_plan": (s.get("graduation_plan") or "").strip(),
                    "enrollment_label_ar": _enrollment_label_ar(s.get("enrollment_status")),
                    "status_action_period": _format_status_action_period(
                        s.get("status_changed_term"), s.get("status_changed_year")
                    )
                    or "—",
                    "status_reason": (s.get("status_reason") or "").strip(),
                    "status_changed_at": (s.get("status_changed_at") or "") or "—",
                }
            )
        generated_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        summary = students_filter_summary_ar(request)
        html = render_template(
            "export_students.html",
            students=rows,
            rows=rows,
            filter_summary=summary,
            generated_at=generated_at,
        )
        return pdf_response_from_html(html, filename_prefix="students")
    except Exception:
        current_app.logger.exception("students_export_pdf failed")
        return jsonify({"status": "error", "message": "فشل التصدير إلى PDF"}), 500

@students_bp.route("/import/excel", methods=["POST"])
@login_required
def students_import_excel():
    f = request.files.get("file")
    if not f:
        return jsonify({"status":"error","message":"file required"}), 400
    try:
        df = pd.read_excel(f)
        df.columns = [c.lower() for c in df.columns]
        if not {"student_id","student_name"}.issubset(df.columns):
            return jsonify({"status":"error","message":"Columns required: student_id, student_name"}), 400
        rows = df.to_dict(orient="records")
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            for r in rows:
                sid = normalize_sid(r.get("student_id"))
                name = r.get("student_name") or ""
                cur.execute("INSERT OR REPLACE INTO students (student_id, student_name) VALUES (?,?)", (sid, name))
            conn.commit()
        return jsonify({"status":"ok","imported":len(rows)}), 200
    except Exception as e:
        current_app.logger.exception("students_import_excel failed")
        return jsonify({"status":"error","message":str(e)}), 500


def compute_timetable_conflicts(conn):
    """Compute conflicts given an open sqlite3 connection.
    Returns list of conflict dicts analogous to the /timetable/conflicts route (but without jsonify)."""
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # detect table
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    table_name = None
    for t in ("timetable", "schedule", "sessions"):
        if t in tables:
            table_name = t
            break
    if not table_name:
        table_name = tables[0] if tables else "timetable"

    cols_info = cur.execute(f"PRAGMA table_info({table_name})").fetchall()
    col_names = [c[1] for c in cols_info]

    has_start = 'start_time' in col_names and 'end_time' in col_names

    select_cols = []
    if 'day' in col_names:
        select_cols.append("COALESCE(day, '') AS day")
    else:
        select_cols.append("COALESCE(weekday, '') AS day")
    if has_start:
        select_cols.append("COALESCE(start_time, '') AS start_time")
        select_cols.append("COALESCE(end_time, '') AS end_time")
    elif 'time' in col_names:
        select_cols.append("COALESCE(time, '') AS time_single")
    elif 'time_range' in col_names:
        select_cols.append("COALESCE(time_range, '') AS time_single")
    elif 'timeslot' in col_names:
        select_cols.append("COALESCE(timeslot, '') AS time_single")
    else:
        select_cols.append("COALESCE(time, '') AS time_single")

    for cname in ("room", "course_name", "student_id", "section", "note"):
        if cname in col_names:
            select_cols.append(f"COALESCE({cname}, '') AS {cname}")
        else:
            select_cols.append(f"'' AS {cname}")

    q = f"SELECT {', '.join(select_cols)} FROM {table_name}"
    try:
        rows = cur.execute(q).fetchall()
    except Exception:
        return []

    slots = {}
    for r in rows:
        rowd = dict(r)
        day = rowd.get("day", "") or ""
        if "start_time" in rowd and "end_time" in rowd:
            start = rowd.get("start_time", "") or ""
            end = rowd.get("end_time", "") or ""
        else:
            ts = rowd.get("time_single", "") or ""
            start, end = parse_time_range(ts)
        room = rowd.get("room", "") or ""
        course = rowd.get("course_name", "") or ""
        sid = rowd.get("student_id", "") or ""
        section = rowd.get("section", "") or ""
        note = rowd.get("note", "") or ""

        key = f"{day}|{start}|{end}|{room}"
        slots.setdefault(key, {"day": day, "start_time": start, "end_time": end, "room": room, "entries": []})
        slots[key]["entries"].append({
            "student_id": sid,
            "student_name": "",
            "course_name": course,
            "section": section,
            "note": note
        })

    student_ids = sorted({e["student_id"] for s in slots.values() for e in s["entries"] if e["student_id"]})
    name_map = {}
    if student_ids:
        try:
            q2 = "SELECT student_id, COALESCE(student_name,'') as student_name FROM students WHERE student_id IN ({})".format(
                ",".join("?" for _ in student_ids)
            )
            rows2 = cur.execute(q2, student_ids).fetchall()
            name_map = {r["student_id"]: r["student_name"] for r in rows2}
        except Exception:
            name_map = {}

    conflicts = []
    for k, s in slots.items():
        entries = s["entries"]
        unique_students = {e["student_id"] for e in entries if e["student_id"]}
        unique_course_sections = {(e["course_name"], e.get("section", "")) for e in entries}
        if len(entries) > 1 and (len(unique_students) > 1 or len(unique_course_sections) > 1):
            for e in entries:
                sid = e.get("student_id") or ""
                e["student_name"] = name_map.get(sid, "")
            s["key"] = k
            conflicts.append(s)

    return conflicts


def compute_per_student_conflicts(conn):
    """
    Compute conflicts where a student has 2+ different courses at the same day/time.
    Returns list of dicts: { student_id, day, time, conflicting_sections, conflict_id }.
    Uses optimized_schedule if it has rows (لمطابقة شبكة النتائج)، وإلا schedule.
    """
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # مصدر أوقات المقررات: optimized_schedule (المعروض في النتائج) إن وُجد، وإلا schedule
    schedule_rows = []
    try:
        schedule_rows = cur.execute("""
            SELECT DISTINCT course_name, day, time 
            FROM optimized_schedule 
            WHERE course_name IS NOT NULL AND course_name != '' 
            AND day IS NOT NULL AND day != '' 
            AND time IS NOT NULL AND time != ''
        """).fetchall()
    except Exception:
        pass
    if not schedule_rows:
        try:
            schedule_rows = cur.execute("""
                SELECT DISTINCT course_name, day, time 
                FROM schedule 
                WHERE course_name IS NOT NULL AND course_name != '' 
                AND day IS NOT NULL AND day != '' 
                AND time IS NOT NULL AND time != ''
            """).fetchall()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Error reading schedule table: %s", e)
            return []

    if not schedule_rows:
        return []

    # Build mapping: course_name -> list of (day, time) tuples
    course_schedule = defaultdict(list)
    for row in schedule_rows:
        course_name = (row['course_name'] or '').strip()
        day = (row['day'] or '').strip()
        time = (row['time'] or '').strip()
        if course_name and day and time:
            course_schedule[course_name].append((day, time))

    # Helper to convert time string to minutes
    def time_to_minutes(time_str):
        """Convert HH:MM to minutes since midnight"""
        try:
            parts = str(time_str).strip().split(':')
            if len(parts) >= 2:
                h = int(parts[0])
                m = int(parts[1])
                return h * 60 + m
        except Exception:
            pass
        return None

    def parse_time_range(time_str):
        """Parse time range like '09:00-11:00' or '11:00-09:00'"""
        if not time_str:
            return None, None
        time_str = str(time_str).strip()
        # Try different separators
        for sep in ['-', '–', '—', '/', ' to ']:
            if sep in time_str:
                parts = [p.strip() for p in time_str.split(sep, 1)]
                if len(parts) == 2:
                    start_min = time_to_minutes(parts[0])
                    end_min = time_to_minutes(parts[1])
                    if start_min is not None and end_min is not None:
                        # Handle reversed times like '13:00-09:00'
                        if end_min < start_min:
                            start_min, end_min = end_min, start_min
                        return start_min, end_min
        # Single time
        single_min = time_to_minutes(time_str)
        return single_min, single_min

    # Get all student registrations
    try:
        registrations = cur.execute("""
            SELECT DISTINCT student_id, course_name 
            FROM registrations 
            WHERE student_id IS NOT NULL 
            AND student_id != '' 
            AND course_name IS NOT NULL 
            AND course_name != ''
        """).fetchall()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error reading registrations: {e}")
        return []

    # Build student schedule: student_id -> day -> list of courses with times
    student_schedule = defaultdict(lambda: defaultdict(list))
    for reg in registrations:
        student_id = (reg['student_id'] or '').strip()
        course_name = (reg['course_name'] or '').strip()
        
        # Only include courses that are in the schedule
        if course_name not in course_schedule:
            continue
        
        # Add all schedule entries for this course
        for day, time_str in course_schedule[course_name]:
            start_min, end_min = parse_time_range(time_str)
            student_schedule[student_id][day].append({
                'course_name': course_name,
                'time_str': time_str,
                'start_min': start_min,
                'end_min': end_min
            })

    # Find conflicts: for each student+day, check for overlapping courses
    conflicts = []
    conflict_id = 0
    for student_id, days_dict in student_schedule.items():
        for day, courses in days_dict.items():
            # Check all pairs of courses for time overlap
            n = len(courses)
            for i in range(n):
                for j in range(i + 1, n):
                    course1 = courses[i]
                    course2 = courses[j]
                    
                    # Skip if same course
                    if course1['course_name'] == course2['course_name']:
                        continue
                    
                    # Check for time overlap
                    has_overlap = False
                    if (course1['start_min'] is not None and course1['end_min'] is not None and
                        course2['start_min'] is not None and course2['end_min'] is not None):
                        # Check if time ranges overlap
                        latest_start = max(course1['start_min'], course2['start_min'])
                        earliest_end = min(course1['end_min'], course2['end_min'])
                        if latest_start < earliest_end:
                            has_overlap = True
                    elif course1['time_str'] == course2['time_str'] and course1['time_str']:
                        # Same time string
                        has_overlap = True
                    
                    if has_overlap:
                        conflict_id += 1
                        conflicting_courses = sorted([course1['course_name'], course2['course_name']])
                        conflicts.append({
                            'conflict_id': conflict_id,
                            'student_id': student_id,
                            'day': day,
                            'time': course1['time_str'] or course2['time_str'] or '',
                            'conflicting_sections': ', '.join(conflicting_courses)
                        })

    return conflicts


def recompute_conflict_report(conn):
    """
    إعادة حساب تعارضات الجدول لجميع الطلبة وملء جدول conflict_report من جديد.
    يُستدعى بعد تغيير التسجيلات أو الجدول لضمان ظهور التعارضات (مثل طالبة حنين).
    """
    cur = conn.cursor()
    conflicts = compute_per_student_conflicts(conn)
    try:
        cur.execute("DELETE FROM conflict_report")
        for c in conflicts:
            cur.execute(
                """INSERT INTO conflict_report (student_id, day, time, conflicting_sections) VALUES (?, ?, ?, ?)""",
                (
                    c.get("student_id") or "",
                    c.get("day") or "",
                    c.get("time") or "",
                    c.get("conflicting_sections") or "",
                ),
            )
        conn.commit()
        return len(conflicts)
    except Exception:
        conn.rollback()
        raise


def compute_student_conflicts(conn):
    """Detect conflicts where a student has 2+ schedule entries at the same day/time.
    Uses registrations JOIN schedule to detect overlapping enrollments. Returns flat rows:
    [{ student_id, day, time, conflicting_sections }, ...]
    """
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # Build a flexible day/time expression covering common column names
    day_expr = "COALESCE(s.day, s.weekday, '')"
    time_expr = "COALESCE(s.start_time, s.time, s.time_range, s.timeslot, '')"

    q = f"""
        SELECT r.student_id as student_id,
               {day_expr} as day,
               {time_expr} as time,
               GROUP_CONCAT(s.course_name || CASE WHEN COALESCE(s.section,'')<>'' THEN '('||COALESCE(s.section,'')||')' ELSE '' END, ' | ') as conflicting_sections,
               COUNT(*) as cnt
        FROM registrations r
        JOIN schedule s ON r.course_name = s.course_name
        WHERE COALESCE(r.student_id, '') <> ''
        GROUP BY r.student_id, day, time
        HAVING COUNT(*) > 1
    """
    try:
        rows = cur.execute(q).fetchall()
    except Exception:
        return []

    out = []
    for r in rows:
        out.append({
            'student_id': r['student_id'] or '',
            'day': r['day'] or '',
            'time': r['time'] or '',
            'conflicting_sections': r['conflicting_sections'] or ''
        })
    return out
