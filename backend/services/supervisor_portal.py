"""بوابة المشرف الأكاديمي — لوحة الإشراف، استبيانات التعبئة، تقارير الإرشاد."""

from __future__ import annotations

import datetime
from typing import Any

from flask import Blueprint, jsonify, request, session

from backend.core.auth import (
    SESSION_ACTIVE_MODE,
    _normalize_role,
    login_required,
    supervisor_portal_ui_allowed,
)
from backend.services.multi_surveys import list_pending_for_user, survey_respondent_role
from backend.services.survey_platform_routes import (
    _count_supervisor_templates,
    _count_templates_for_respondent,
    _enrich_pending_surveys,
    _session_active_mode,
    _session_payload,
    _supervisor_report_status,
    build_survey_hub_status,
)
from backend.services.quality_metrics import term_label_from_conn
from backend.services import utilities as db_util
from backend.services.utilities import pdf_response_from_html

supervisor_portal_bp = Blueprint("supervisor_portal", __name__)


def _forbidden():
    return jsonify({"status": "error", "message": "غير مصرح — هذه الصفحة للمشرف الأكاديمي فقط"}), 403


def _instructor_profile(conn, instructor_id: int) -> dict | None:
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT i.id, COALESCE(i.name, '') AS name, i.department_id,
               COALESCE(d.name_ar, d.code, '') AS department_name
        FROM instructors i
        LEFT JOIN departments d ON d.id = i.department_id
        WHERE i.id = ? LIMIT 1
        """,
        (int(instructor_id),),
    ).fetchone()
    if not row:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    return {"id": row[0], "name": row[1] or "", "department_id": row[2], "department_name": row[3] or ""}


def _serialize_pending(pending: list) -> list[dict]:
    out = []
    for p in pending or []:
        intro = p.get("intro") if isinstance(p.get("intro"), dict) else {}
        out.append({
            "code": p.get("code") or "",
            "title_ar": p.get("title_ar") or "",
            "fill_url": p.get("fill_url") or "",
            "semester": p.get("semester") or "",
            "intro": {
                "subtitle_ar": intro.get("subtitle_ar") or "",
                "duration_hint": intro.get("duration_hint") or "",
            },
        })
    return out


def _failed_course_counts(conn, student_ids: list[str]) -> dict[str, int]:
    """عدد مقررات راسب فيها كل طالب (تقريبي من registrations.final_grade)."""
    if not student_ids:
        return {}
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in student_ids)
    try:
        rows = cur.execute(
            f"""
            SELECT student_id, COUNT(*) AS cnt
            FROM registrations
            WHERE student_id IN ({placeholders})
              AND lower(trim(COALESCE(final_grade, ''))) IN ('f', 'راسب', 'fail', 'failed')
            GROUP BY student_id
            """,
            tuple(student_ids),
        ).fetchall()
    except Exception:
        return {}
    out: dict[str, int] = {}
    for r in rows:
        sid = (r[0] if not hasattr(r, "keys") else r["student_id"]) or ""
        cnt = int((r[1] if not hasattr(r, "keys") else r["cnt"]) or 0)
        if sid:
            out[str(sid).strip()] = cnt
    return out


def _load_supervised_students(conn, instructor_id: int) -> list[dict]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT ss.student_id, COALESCE(s.student_name, '') AS student_name
        FROM student_supervisor ss
        LEFT JOIN students s ON s.student_id = ss.student_id
        WHERE ss.instructor_id = ?
        ORDER BY ss.student_id
        """,
        (int(instructor_id),),
    ).fetchall()
    students = []
    for r in rows:
        if hasattr(r, "keys"):
            students.append({"student_id": r["student_id"], "student_name": r["student_name"] or ""})
        else:
            students.append({"student_id": r[0], "student_name": r[1] or ""})
    return students


def _resolve_supervisor_department_id(conn, role: str, session_data: dict) -> int | None:
    role_n = _normalize_role((role or "").strip())
    uname = (session_data.get("user") or session_data.get("username") or "").strip()
    cur = conn.cursor()
    if uname:
        row = cur.execute(
            "SELECT department_id FROM users WHERE lower(username)=lower(?) LIMIT 1",
            (uname,),
        ).fetchone()
        if row and row[0] not in (None, ""):
            try:
                return int(row[0])
            except (TypeError, ValueError):
                pass
    iid = session_data.get("instructor_id")
    if iid and role_n in ("instructor", "head_of_department", "supervisor", "college_dean", "academic_vice_dean"):
        try:
            iid_i = int(iid)
        except (TypeError, ValueError):
            iid_i = 0
        if iid_i:
            inst = cur.execute(
                "SELECT department_id FROM instructors WHERE id = ? LIMIT 1",
                (iid_i,),
            ).fetchone()
            if inst and inst[0] not in (None, ""):
                try:
                    return int(inst[0])
                except (TypeError, ValueError):
                    pass
    return None


def build_supervisor_quality_context(
    conn,
    *,
    role: str,
    session_data: dict,
    active_mode: str,
    semester: str | None = None,
) -> dict[str, Any]:
    sem = (semester or "").strip() or term_label_from_conn(conn)
    dept_id = _resolve_supervisor_department_id(conn, role, session_data)
    iid = session_data.get("instructor_id")
    try:
        iid_int = int(iid) if iid not in (None, "") else 0
    except (TypeError, ValueError):
        iid_int = 0
    profile = _instructor_profile(conn, iid_int) if iid_int else None
    eff = survey_respondent_role(role, active_mode)

    pending = list_pending_for_user(
        conn,
        user_role=role,
        session_data=session_data,
        semester=sem,
        department_id=dept_id,
        active_mode=active_mode,
    )
    pending = [p for p in pending if p.get("pending_kind") != "course_eval"]
    pending = _enrich_pending_surveys(pending)

    supervisor_template_count = _count_supervisor_templates(conn)
    dept_missing = dept_id is None and supervisor_template_count > 0
    hub_status = build_survey_hub_status(
        conn,
        role=role,
        session_data=session_data,
        semester=sem,
        department_id=dept_id,
        active_mode=active_mode,
        pending=pending,
        supervisor_effective=True,
        supervisor_template_count=supervisor_template_count,
        dept_missing=dept_missing,
    )
    template_count = _count_templates_for_respondent(conn, eff)
    supervisor_report = _supervisor_report_status(conn, iid_int or None, sem)

    return {
        "instructor_id": iid_int or None,
        "instructor_name": (profile or {}).get("name") or "",
        "department_name": (profile or {}).get("department_name") or "",
        "term_label": sem,
        "respondent_role": eff,
        "surveys": {
            "pending": _serialize_pending(pending),
            "pending_count": len(pending),
            "template_count": template_count,
            "all_done": len(pending) == 0 and template_count > 0,
            "hub_status": hub_status,
            "fill_hub_url": "/academic_quality/surveys",
        },
        "supervisor_report": supervisor_report,
        "links": {
            "surveys_fill": "/academic_quality/surveys",
            "quality_hub": "/academic_quality/supervisor/quality-hub",
            "advising_report": "/supervisor_quality_report_page",
            "supervisor_dashboard": "/supervisor_dashboard",
        },
    }


def build_supervisor_dashboard_context(
    conn,
    *,
    role: str,
    session_data: dict,
    active_mode: str,
    semester: str | None = None,
) -> dict[str, Any]:
    sem = (semester or "").strip() or term_label_from_conn(conn)
    iid = session_data.get("instructor_id")
    try:
        iid_int = int(iid) if iid not in (None, "") else 0
    except (TypeError, ValueError):
        iid_int = 0
    profile = _instructor_profile(conn, iid_int) if iid_int else None
    quality = build_supervisor_quality_context(
        conn, role=role, session_data=session_data, active_mode=active_mode, semester=sem,
    )
    students = _load_supervised_students(conn, iid_int) if iid_int else []
    failed_map = _failed_course_counts(conn, [s["student_id"] for s in students if s.get("student_id")])
    at_risk_threshold = 1
    for st in students:
        sid = (st.get("student_id") or "").strip()
        fc = int(failed_map.get(sid) or 0)
        st["failed_courses_count"] = fc
        st["at_risk"] = fc >= at_risk_threshold

    pending_count = int((quality.get("surveys") or {}).get("pending_count") or 0)
    report = quality.get("supervisor_report") or {}
    report_row = {}
    if iid_int:
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT at_risk_students_count, intervention_actions, success_rate, submitted_at
            FROM supervisor_quality_reports
            WHERE supervisor_instructor_id = ? AND semester = ?
            LIMIT 1
            """,
            (iid_int, sem),
        ).fetchone()
        if row:
            report_row = {
                "at_risk_students_count": row[0],
                "intervention_actions": row[1] or "",
                "success_rate": row[2],
                "submitted_at": row[3],
            }
    report_done = bool(report.get("submitted"))
    tasks = []
    if not iid_int:
        tasks.append({
            "level": "warning",
            "title": "ربط حساب الأستاذ",
            "message": "لم يُربط instructor_id — تواصل مع الإدارة.",
            "href": None,
        })
    if pending_count > 0:
        tasks.append({
            "level": "warning",
            "title": "استبيانات معلّقة",
            "message": f"لديك {pending_count} استبيان(ات) مطلوبة لهذا الفصل.",
            "href": "/academic_quality/surveys",
        })
    if not report_done and iid_int:
        tasks.append({
            "level": "info",
            "title": "تقرير الإرشاد الكمي",
            "message": "لم يُرسَل تقرير الإرشاد لهذا الفصل بعد.",
            "href": "/supervisor_quality_report_page",
        })
    if pending_count == 0 and report_done and iid_int:
        tasks.append({
            "level": "success",
            "title": "اكتمل المطلوب",
            "message": "أكملت الاستبيانات وتقرير الإرشاد لهذا الفصل.",
            "href": "/academic_quality/supervisor/quality-hub",
        })

    at_risk_students = [s for s in students if s.get("at_risk")]
    return {
        "instructor_id": iid_int or None,
        "instructor_name": (profile or {}).get("name") or "",
        "term_label": sem,
        "student_count": len(students),
        "at_risk_count": len(at_risk_students),
        "students": students,
        "tasks": tasks,
        "surveys_pending_count": pending_count,
        "report_submitted": report_done,
        "report_submitted_at": report.get("submitted_at"),
        "report_details": report_row,
        "quality_summary": quality,
    }


def render_supervisor_summary_pdf_html(ctx: dict) -> str:
    sem = ctx.get("term_label") or ""
    name = ctx.get("instructor_name") or ""
    students = ctx.get("students") or []
    rows = "".join(
        f"<tr><td>{s.get('student_id', '')}</td><td>{s.get('student_name', '')}</td>"
        f"<td>{s.get('failed_courses_count', 0)}</td>"
        f"<td>{'نعم' if s.get('at_risk') else '—'}</td></tr>"
        for s in students
    )
    report = ctx.get("report_details") or {}
    return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<style>body{{font-family:Cairo,sans-serif;padding:24px}} table{{width:100%;border-collapse:collapse}}
th,td{{border:1px solid #ccc;padding:6px;font-size:12px}} h1{{font-size:18px}}</style></head><body>
<h1>ملخص الإشراف الأكاديمي — {sem}</h1>
<p><strong>المشرف:</strong> {name}</p>
<p>عدد الطلبة: {ctx.get('student_count', 0)} · معرّضون للخطر: {ctx.get('at_risk_count', 0)}</p>
<p>استبيانات معلّقة: {ctx.get('surveys_pending_count', 0)} · تقرير الإرشاد: {'مُرسَل' if ctx.get('report_submitted') else 'غير مُرسَل'}</p>
<h2>الطلبة</h2>
<table><thead><tr><th>الرقم</th><th>الاسم</th><th>مقررات راسبة</th><th>معرّض</th></tr></thead>
<tbody>{rows or '<tr><td colspan="4">لا طلبة</td></tr>'}</tbody></table>
<h2>تقرير الإرشاد (آخر إرسال)</h2>
<p>متعثرون: {report.get('at_risk_students_count', '—')} · نسبة النجاح: {report.get('success_rate', '—')}%</p>
<p class="small">تاريخ الإنشاء: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</body></html>"""


@supervisor_portal_bp.route("/quality_context", methods=["GET"])
@login_required
def api_supervisor_quality_context():
    if not supervisor_portal_ui_allowed():
        return _forbidden()
    role = _normalize_role((session.get("user_role") or "").strip())
    active_mode = _session_active_mode(role)
    sem = (request.args.get("semester") or "").strip()
    with db_util.get_connection() as conn:
        data = build_supervisor_quality_context(
            conn,
            role=role,
            session_data=_session_payload(),
            active_mode=active_mode,
            semester=sem or None,
        )
    return jsonify({"status": "ok", **data})


@supervisor_portal_bp.route("/dashboard_context", methods=["GET"])
@login_required
def api_supervisor_dashboard_context():
    if not supervisor_portal_ui_allowed():
        return _forbidden()
    role = _normalize_role((session.get("user_role") or "").strip())
    active_mode = _session_active_mode(role)
    sem = (request.args.get("semester") or "").strip()
    with db_util.get_connection() as conn:
        data = build_supervisor_dashboard_context(
            conn,
            role=role,
            session_data=_session_payload(),
            active_mode=active_mode,
            semester=sem or None,
        )
    return jsonify({"status": "ok", **data})


@supervisor_portal_bp.route("/summary.pdf", methods=["GET"])
@login_required
def api_supervisor_summary_pdf():
    if not supervisor_portal_ui_allowed():
        return _forbidden()
    role = _normalize_role((session.get("user_role") or "").strip())
    active_mode = _session_active_mode(role)
    with db_util.get_connection() as conn:
        ctx = build_supervisor_dashboard_context(
            conn,
            role=role,
            session_data=_session_payload(),
            active_mode=active_mode,
        )
    html = render_supervisor_summary_pdf_html(ctx)
    return pdf_response_from_html(html, filename_prefix="supervisor_summary")
