import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models.models import Student
from flask import Blueprint, request, jsonify, render_template, current_app, send_file, session
from backend.core.auth import login_required, role_required
from collections import defaultdict
import sqlite3, pandas as pd, io, datetime
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

students_bp = Blueprint("students", __name__)

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
        try:
            from backend.services.electives import check_electives_requirement
        except Exception:
            check_electives_requirement = None
        rows = cur.execute("SELECT student_id, COALESCE(student_name,'') FROM students ORDER BY student_name, student_id").fetchall()
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
# تقرير سجل الإضافة والإسقاط (المواد المضافة والمسقطة + التواريخ)
# -----------------------------
def _registration_changes_report_items(conn, date_from=None, date_to=None, student_id=None, action=None, course_name_like=None):
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
        items = _registration_changes_report_items(
            conn, date_from=date_from, date_to=date_to,
            student_id=student_id, action=action, course_name_like=course_name
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
        items = _registration_changes_report_items(
            conn, date_from=date_from, date_to=date_to,
            student_id=student_id, action=action, course_name_like=course_name
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
        items = _registration_changes_report_items(
            conn, date_from=date_from, date_to=date_to,
            student_id=student_id, action=action, course_name_like=course_name
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


def _best_grades_map(conn, student_id=None, course_name_like=None):
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


@students_bp.route("/uncompleted_courses_report")
@role_required("admin", "admin_main", "head_of_department", "supervisor")
def uncompleted_courses_report_api():
    """تقرير: مقررات الطالب غير المنجزة (لا يوجد أي نجاح للمقرر)."""
    sid = normalize_sid(request.args.get("student_id"))
    if not sid:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400
    with get_connection() as conn:
        best = _best_grades_map(conn, student_id=sid)
        items = [v for v in best.values() if not v.get("passed")]
        items = sorted(items, key=lambda x: (x.get("course_name") or ""))
    return jsonify({"status": "ok", "student_id": sid, "items": items})


@students_bp.route("/uncompleted_courses_report/excel")
@role_required("admin", "admin_main", "head_of_department", "supervisor")
def uncompleted_courses_report_excel():
    sid = normalize_sid(request.args.get("student_id"))
    r = uncompleted_courses_report_api()
    payload = r[0].get_json() if isinstance(r, tuple) else r.get_json()
    items = payload.get("items", []) if payload else []
    df = pd.DataFrame(items or [])
    # ترتيب أعمدة ودية
    cols = ["student_id", "student_name", "course_name", "course_code", "units", "best_grade_display", "attempts", "best_semester"]
    if not df.empty:
        keep = [c for c in cols if c in df.columns] + [c for c in df.columns if c not in cols]
        df = df[keep]
    return excel_response_from_df(df, filename_prefix=f"uncompleted_courses_{sid or 'student'}")


@students_bp.route("/uncompleted_courses_report/pdf")
@role_required("admin", "admin_main", "head_of_department", "supervisor")
def uncompleted_courses_report_pdf():
    sid = normalize_sid(request.args.get("student_id"))
    r = uncompleted_courses_report_api()
    payload = r[0].get_json() if isinstance(r, tuple) else r.get_json()
    items = payload.get("items", []) if payload else []
    rows_html = ""
    for it in items:
        rows_html += (
            "<tr>"
            f"<td>{_h(it.get('course_name'))}</td>"
            f"<td>{_h(it.get('course_code'))}</td>"
            f"<td style='text-align:center'>{_h(it.get('units'))}</td>"
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
      <p>المقرر يُعتبر منجزاً إذا وُجدت أي محاولة ناجحة (درجة ≥ 50 أو "ناجح").</p>
      <table>
        <thead>
          <tr>
            <th>المقرر</th><th>الرمز</th><th>الوحدات</th><th>أفضل درجة</th><th>المحاولات</th><th>آخر فصل (مرجعي)</th>
          </tr>
        </thead>
        <tbody>
          {rows_html or "<tr><td colspan='6' style='text-align:center'>لا توجد بيانات</td></tr>"}
        </tbody>
      </table>
    </body>
    </html>
    """
    return pdf_response_from_html(html, filename_prefix=f"uncompleted_courses_{sid or 'student'}")


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
        best = _best_grades_map(conn, student_id=None, course_name_like=course_name)
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
        best = _best_grades_map(conn, student_id=None, course_name_like=course_name)
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
        best = _best_grades_map(conn, student_id=None, course_name_like=course_name)
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
      <h2>تقرير شامل المقررات غير المنجزة</h2>
      <p>يُعتبر المقرر منجزاً إذا وُجدت أي محاولة ناجحة (درجة ≥ 50 أو نص "ناجح"). هذا التقرير يعرض المقررات غير المنجزة لدى الطلبة (لا توجد أي محاولة ناجحة).</p>
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

# -----------------------------
# CRUD أساسي للطلاب
# -----------------------------
@students_bp.route("/list")
@login_required
def list_students():
    """جلب قائمة الطلاب - يستخدم Service Layer. استخدم ?active_only=1 للتسجيل وخطط التسجيل (لا يُظهر سحب ملف/موقوف قيد/خريج)."""
    try:
        from backend.core.services import StudentService
        from backend.core.exceptions import AppException
        
        active_only = request.args.get("active_only", "").lower() in ("1", "true", "yes")
        join_term = (request.args.get("join_term") or "").strip()
        join_year = (request.args.get("join_year") or "").strip()
        students = StudentService.get_all_students(active_only=active_only)
        if join_term:
            students = [s for s in students if (s.get("join_term") or "").strip() == join_term]
        if join_year:
            students = [s for s in students if (s.get("join_year") or "").strip() == join_year]
        # تحويل إلى كائنات Student للتوافق مع الكود القديم مع إضافة حالة القيد كحقول إضافية
        students_objects = []
        for s in students:
            obj = Student(s["student_id"], s["student_name"])
            # إرفاق حالة القيد وحقولها كخصائص إضافية
            setattr(obj, "enrollment_status", s.get("enrollment_status", "active"))
            setattr(obj, "status_changed_at", s.get("status_changed_at"))
            setattr(obj, "status_reason", s.get("status_reason", ""))
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
            return jsonify([{"student_id": r[0], "student_name": r[1]} for r in rows])
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
            return jsonify([{"student_id": r[0], "student_name": r[1]} for r in rows])
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
@role_required("admin")
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

        result = StudentService.update_enrollment_status(
            student_id=sid,
            status=status,
            changed_at=changed_at,
            reason=reason or "",
            phone=phone,
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
    courses = data.get("courses")
    if courses is None:
        courses = data.get("registrations", [])
    if courses is None:
        courses = []
    if not sid:
        return jsonify({"status": "error", "message": "student_id مطلوب"}), 400
    if not isinstance(courses, list):
        return jsonify({"status": "error", "message": "courses/registrations يجب أن تكون قائمة"}), 400

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
            blocked = {}
            if courses:
                placeholders = ",".join("?" for _ in courses)
                q = f"SELECT course_name, required_course_name FROM prereqs WHERE course_name IN ({placeholders})"
                try:
                    rows = cur.execute(q, courses).fetchall()
                except Exception:
                    current_app.logger.exception("prereqs query failed")
                    rows = []
                prereq_map = defaultdict(list)
                for course_name, required in rows:
                    prereq_map[course_name].append(required)

                for course in courses:
                    reqs = prereq_map.get(course, [])
                    missing = []
                    for r in reqs:
                        old = cur.execute(
                            "SELECT grade FROM grades WHERE student_id = ? AND course_name = ? LIMIT 1",
                            (sid, r)
                        ).fetchone()
                        if old is None or old[0] is None:
                            missing.append(r)
                    if missing:
                        blocked[course] = missing

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

                return jsonify({"status": "ok", "message": "تم حفظ التسجيلات"}), 200
            except Exception as e:
                conn.rollback()
                current_app.logger.exception("insert registrations failed")
                return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        current_app.logger.exception("save_registrations outer failure")
        return jsonify({"status": "error", "message": str(e)}), 500

@students_bp.route("/get_registrations")
@login_required
def get_registrations():
    student_id = normalize_sid(request.args.get("student_id"))
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            # تقييد المشرف: لا يرى تسجيلات إلا لطلبته المسندين إليه
            user_role = session.get("user_role")
            if user_role == "supervisor":
                instructor_id = session.get("instructor_id")
                if not instructor_id:
                    return jsonify([]), 200
                if not student_id:
                    # منع إرجاع جميع التسجيلات للمشرف
                    return jsonify([]), 200
                ok = cur.execute(
                    "SELECT 1 FROM student_supervisor WHERE student_id = ? AND instructor_id = ? LIMIT 1",
                    (student_id, instructor_id),
                ).fetchone()
                if not ok:
                    return jsonify([]), 200
            if student_id:
                rows = cur.execute("SELECT course_name FROM registrations WHERE student_id = ?", (student_id,)).fetchall()
                return jsonify([r[0] for r in rows])
            else:
                rows = cur.execute("SELECT student_id, course_name FROM registrations").fetchall()
                return jsonify([{"student_id": r[0], "course_name": r[1]} for r in rows])
    except Exception:
        current_app.logger.exception("get_registrations failed")
        return jsonify([])

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
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cols = [r[1] for r in cur.execute("PRAGMA table_info(students)").fetchall()]
            has_uni = 'university_number' in cols

            if has_uni:
                rows = cur.execute("""
                    SELECT r.student_id,
                           COALESCE(s.student_name, '') AS student_name,
                           COALESCE(s.university_number, '') AS university_number,
                           r.course_name,
                           COALESCE(c.course_code, '') AS course_code,
                           COALESCE(c.units, 0) AS units
                    FROM registrations r
                    LEFT JOIN students s ON r.student_id = s.student_id
                    LEFT JOIN courses c ON r.course_name = c.course_name
                    ORDER BY r.student_id, r.course_name
                """).fetchall()
            else:
                rows = cur.execute("""
                    SELECT r.student_id,
                           COALESCE(s.student_name, '') AS student_name,
                           '' AS university_number,
                           r.course_name,
                           COALESCE(c.course_code, '') AS course_code,
                           COALESCE(c.units, 0) AS units
                    FROM registrations r
                    LEFT JOIN students s ON r.student_id = s.student_id
                    LEFT JOIN courses c ON r.course_name = c.course_name
                    ORDER BY r.student_id, r.course_name
                """).fetchall()

        data = []
        for r in rows:
            data.append({
                "student_id": r[0] or "",
                "student_name": r[1] or "",
                "university_number": r[2] or "",
                "course_name": r[3] or "",
                "course_code": r[4] or "",
                "units": int(r[5]) if r[5] is not None else 0
            })
        df = pd.DataFrame(data, columns=["student_id","student_name","university_number","course_name","course_code","units"])
        return excel_response_from_df(df, filename_prefix="registrations")
    except Exception:
        current_app.logger.exception("export_registrations_excel failed")
        return jsonify({"status":"error","message":"فشل التصدير"}), 500


@students_bp.route("/export/attendance")
@login_required
def export_attendance_excel():
    """
    تصدير سجلات الحضور/الغياب في ملف Excel متعدد الأوراق.
    يسمح بتحديد مقررات متعددة (?course=اسم1&course=اسم2) وتحديد عدد الأسابيع (?weeks=10).
    """
    raw_courses = request.args.getlist("course") or request.args.getlist("courses")
    if not raw_courses:
        single_courses = request.args.get("courses") or request.args.get("course")
        if single_courses:
            raw_courses = [single_courses]

    def _normalize_courses(values):
        out = []
        for val in values or []:
            if not val:
                continue
            parts = [p.strip() for p in str(val).split(",") if p.strip()]
            out.extend(parts if len(parts) > 1 else [parts[0]] if parts else [])
        # إزالة التكرار مع الحفاظ على الترتيب
        seen = set()
        ordered = []
        for item in out:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(item)
        return ordered

    selected_courses = _normalize_courses(raw_courses)

    MAX_WEEKS = 30
    DEFAULT_WEEKS = 14
    try:
        weeks = int(str(request.args.get("weeks", DEFAULT_WEEKS)).strip())
    except (TypeError, ValueError):
        weeks = DEFAULT_WEEKS
    if weeks < 1:
        weeks = 1
    if weeks > MAX_WEEKS:
        weeks = MAX_WEEKS

    summaries = []
    frames = []
    missing_courses = []

    try:
        with get_connection() as conn:
            cur = conn.cursor()

            # احصل على جميع المقررات المعروفة
            def _fetch_all_courses():
                names = []
                try:
                    rows = cur.execute("SELECT DISTINCT course_name FROM courses WHERE COALESCE(course_name,'') <> '' ORDER BY course_name").fetchall()
                    names = [r[0] for r in rows if r[0]]
                except Exception:
                    names = []
                if not names:
                    try:
                        rows = cur.execute("SELECT DISTINCT course_name FROM schedule WHERE COALESCE(course_name,'') <> '' ORDER BY course_name").fetchall()
                        names = [r[0] for r in rows if r[0]]
                    except Exception:
                        names = []
                # إزالة التكرار مع الحفاظ على الترتيب (احتياطي)
                seen = set()
                ordered = []
                for item in names:
                    key = item.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    ordered.append(item)
                return ordered

            all_courses = _fetch_all_courses()
            normalized_map = {c.lower(): c for c in all_courses}

            if not selected_courses:
                # لا توجد مقررات محددة: استخدم المقررات التي لديها تسجيلات أولاً
                reg_rows = cur.execute(
                    "SELECT DISTINCT course_name FROM registrations WHERE COALESCE(course_name,'') <> '' ORDER BY course_name"
                ).fetchall()
                auto_courses = [r[0] for r in reg_rows if r[0]]
                if not auto_courses:
                    auto_courses = all_courses
                selected_courses = auto_courses
            else:
                # حاول مطابقة المقررات المحددة مع قاعدة البيانات (مع الحفاظ على الأسماء غير المعروفة كما هي لإظهار ملاحظة)
                resolved = []
                for val in selected_courses:
                    match = normalized_map.get(val.lower())
                    if match:
                        resolved.append(match)
                    else:
                        resolved.append(val)
                        missing_courses.append(val)
                # إزالة التكرار مجدداً مع الحفاظ على الترتيب
                seen_rc = set()
                filtered = []
                for c in resolved:
                    key = c.lower()
                    if key in seen_rc:
                        continue
                    seen_rc.add(key)
                    filtered.append(c)
                selected_courses = filtered

            # إذا ما زالت القائمة فارغة فليس هناك بيانات
            if not selected_courses:
                summaries.append({
                    "المقرر": "لا توجد مقررات",
                    "عدد الطلبة": 0,
                    "عدد الأسابيع": weeks,
                    "ملاحظات": "لا توجد بيانات تسجيل متاحة"
                })
                frames.append(("ملخص", pd.DataFrame(summaries)))
                return excel_response_from_frames(frames, filename_prefix="attendance")

            # حضّر خريطة الطلبة لكل مقرر
            course_students = {c: [] for c in selected_courses}
            course_seen = {c: set() for c in selected_courses}

            placeholders = ",".join("?" for _ in selected_courses)
            reg_query = f"""
                SELECT r.course_name, r.student_id, COALESCE(s.student_name, '') AS student_name
                FROM registrations r
                LEFT JOIN students s ON s.student_id = r.student_id
                {'WHERE r.course_name IN (' + placeholders + ')' if selected_courses else ''}
                ORDER BY r.course_name, COALESCE(s.student_name,''), r.student_id
            """
            reg_params = selected_courses if selected_courses else []
            reg_rows = cur.execute(reg_query, reg_params).fetchall()
            for row in reg_rows:
                cname = row[0]
                sid = normalize_sid(row[1])
                if not cname or not sid:
                    continue
                if cname not in course_students:
                    course_students[cname] = []
                    course_seen[cname] = set()
                if sid in course_seen[cname]:
                    continue
                course_seen[cname].add(sid)
                course_students[cname].append({
                    "student_id": sid,
                    "student_name": row[2] or ""
                })

            # اجلب بيانات الحضور المخزنة إن وجدت
            attendance_map = {}
            if selected_courses:
                att_placeholders = ",".join("?" for _ in selected_courses)
                att_query = f"""
                    SELECT course_name, student_id, week_number, COALESCE(status, '') AS status
                    FROM attendance_records
                    WHERE week_number BETWEEN 1 AND ?
                    {'AND course_name IN (' + att_placeholders + ')' if selected_courses else ''}
                """
                params = [weeks] + (selected_courses if selected_courses else [])
                try:
                    att_rows = cur.execute(att_query, params).fetchall()
                except Exception:
                    att_rows = []
                for row in att_rows:
                    cname, sid, week_no, status = row
                    if not cname or not sid:
                        continue
                    try:
                        week_idx = int(week_no)
                    except (TypeError, ValueError):
                        continue
                    if week_idx < 1 or week_idx > weeks:
                        continue
                    key = (cname, normalize_sid(sid))
                    attendance_map.setdefault(key, {})[week_idx] = status

            # إعداد أوراق العمل
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

            # أضف المقررات المفقودة في الملاحظات
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

        # إضافة ورقة الملخص في البداية
        summary_df = pd.DataFrame(summaries)
        frames.insert(0, ("ملخص", summary_df))

        return excel_response_from_frames(frames, filename_prefix="attendance")
    except Exception:
        current_app.logger.exception("export_attendance_excel failed")
        return jsonify({"status": "error", "message": "فشل تصدير الحضور"}), 500
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

            schedule_course_names = set(
                r[0] for r in cur.execute("SELECT DISTINCT course_name FROM schedule WHERE COALESCE(course_name,'') <> ''").fetchall()
            )
            try:
                all_rows = cur.execute("SELECT course_name, COALESCE(course_code, ''), COALESCE(units, 0) FROM courses").fetchall()
                all_courses = [{"course_name": r[0], "course_code": r[1], "units": r[2]} for r in all_rows]
            except Exception:
                all_rows = cur.execute("SELECT DISTINCT course_name FROM schedule").fetchall()
                all_courses = [{"course_name": r[0], "course_code": "", "units": 0} for r in all_rows]

            all_courses = [c for c in all_courses if c["course_name"] in schedule_course_names]

            try:
                grade_rows = cur.execute("""
                    SELECT course_name, grade FROM grades
                    WHERE student_id = ?
                    GROUP BY course_name
                """, (sid,)).fetchall()
            except Exception:
                grade_rows = cur.execute("SELECT course_name, grade FROM grades WHERE student_id = ?", (sid,)).fetchall()

            grade_map = {r[0]: r[1] for r in grade_rows}

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
        with get_connection() as conn:
            cur = conn.cursor()
            cols = [row[1] for row in cur.execute("PRAGMA table_info(students)").fetchall()]
            sel = "SELECT student_id, student_name"
            if "join_term" in cols:
                sel += ", COALESCE(join_term, '') AS join_term"
            if "join_year" in cols:
                sel += ", COALESCE(join_year, '') AS join_year"
            if "graduation_plan" in cols:
                sel += ", COALESCE(graduation_plan, '') AS graduation_plan"
            sel += " FROM students ORDER BY student_name, student_id"
            rows = cur.execute(sel).fetchall()
            df = pd.DataFrame([dict(r) for r in rows])
        return excel_response_from_df(df, filename_prefix="students")
    except Exception:
        current_app.logger.exception("students_export_excel failed")
        return jsonify({"status": "error", "message": "فشل التصدير"}), 500

@students_bp.route("/export/pdf")
@login_required
def students_export_pdf():
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cols = [row[1] for row in cur.execute("PRAGMA table_info(students)").fetchall()]
            sel = "SELECT student_id, student_name"
            if "join_term" in cols:
                sel += ", COALESCE(join_term, '') AS join_term"
            if "join_year" in cols:
                sel += ", COALESCE(join_year, '') AS join_year"
            if "graduation_plan" in cols:
                sel += ", COALESCE(graduation_plan, '') AS graduation_plan"
            sel += " FROM students ORDER BY student_id"
            rows = cur.execute(sel).fetchall()
            students = [dict(r) for r in rows]
        html = render_template("export_students.html", students=students)
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
