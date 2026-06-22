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
from backend.database.database import table_exists
from backend.services.quality_metrics import term_label_from_conn
from backend.services import utilities as db_util
from backend.services.utilities import pdf_response_from_html, schedule_semester_matches_current_term

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


def _safe_rollback(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def _row_val(row, key: str, idx: int = 0):
    if hasattr(row, "keys"):
        return row[key]
    return row[idx]


def _failed_course_counts(conn, student_ids: list[str]) -> dict[str, int]:
    """عدد مقررات راسب فيها كل طالب (من جدول grades)."""
    if not student_ids or not table_exists(conn, "grades"):
        return {}
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in student_ids)
    try:
        rows = cur.execute(
            f"""
            SELECT student_id, COUNT(DISTINCT course_name) AS cnt
            FROM grades
            WHERE student_id IN ({placeholders})
              AND (
                (grade IS NOT NULL AND grade < 50)
                OR lower(trim(COALESCE(CAST(grade AS TEXT), ''))) IN ('f', 'راسب', 'fail', 'failed')
              )
            GROUP BY student_id
            """,
            tuple(student_ids),
        ).fetchall()
    except Exception:
        _safe_rollback(conn)
        return {}
    out: dict[str, int] = {}
    for r in rows:
        sid = str(_row_val(r, "student_id", 0) or "").strip()
        cnt = int(_row_val(r, "cnt", 1) or 0)
        if sid:
            out[sid] = cnt
    return out


def _load_semester_academic_by_student(
    conn, student_ids: list[str], semester: str,
) -> dict[str, dict[str, Any]]:
    """تسجيلات الفصل وحالة خطة التسجيل لكل طالب."""
    sem = (semester or "").strip()
    base = {
        sid: {
            "registrations_count": 0,
            "registration_courses": [],
            "plan_id": None,
            "plan_status": None,
            "plan_courses_count": 0,
            "plan_courses": [],
        }
        for sid in student_ids
    }
    if not student_ids:
        return base

    cur = conn.cursor()
    placeholders = ",".join("?" for _ in student_ids)
    plan_courses_by_student: dict[str, set[str]] = {sid: set() for sid in student_ids}

    if table_exists(conn, "enrollment_plans"):
        try:
            plan_rows = cur.execute(
                f"""
                SELECT ep.id, ep.student_id, ep.status
                FROM enrollment_plans ep
                INNER JOIN (
                    SELECT student_id, MAX(id) AS max_id
                    FROM enrollment_plans
                    WHERE student_id IN ({placeholders}) AND semester = ?
                    GROUP BY student_id
                ) latest ON latest.max_id = ep.id
                """,
                (*student_ids, sem),
            ).fetchall()
        except Exception:
            _safe_rollback(conn)
            plan_rows = []
        plan_ids: list[int] = []
        plan_id_by_student: dict[str, int] = {}
        for r in plan_rows or []:
            sid = str(_row_val(r, "student_id", 1) or "").strip()
            pid = _row_val(r, "id", 0)
            if not sid or pid in (None, ""):
                continue
            pid_i = int(pid)
            plan_ids.append(pid_i)
            plan_id_by_student[sid] = pid_i
            base[sid]["plan_id"] = pid_i
            base[sid]["plan_status"] = _row_val(r, "status", 2)

        if plan_ids and table_exists(conn, "enrollment_plan_items"):
            ph2 = ",".join("?" for _ in plan_ids)
            try:
                item_rows = cur.execute(
                    f"""
                    SELECT plan_id, course_name
                    FROM enrollment_plan_items
                    WHERE plan_id IN ({ph2})
                    ORDER BY plan_id, course_name
                    """,
                    tuple(plan_ids),
                ).fetchall()
            except Exception:
                _safe_rollback(conn)
                item_rows = []
            courses_by_plan: dict[int, list[str]] = {}
            for r in item_rows or []:
                pid = int(_row_val(r, "plan_id", 0) or 0)
                cn = str(_row_val(r, "course_name", 1) or "").strip()
                if pid and cn:
                    courses_by_plan.setdefault(pid, []).append(cn)
            for sid, pid in plan_id_by_student.items():
                lst = courses_by_plan.get(pid, [])
                plan_courses_by_student[sid] = set(lst)
                base[sid]["plan_courses"] = lst[:12]
                base[sid]["plan_courses_count"] = len(lst)

    if table_exists(conn, "registrations"):
        try:
            reg_rows = cur.execute(
                f"""
                SELECT r.student_id, r.course_name, COALESCE(tg.semester, '') AS group_semester
                FROM registrations r
                LEFT JOIN teaching_groups tg ON tg.id = r.teaching_group_id
                WHERE r.student_id IN ({placeholders})
                ORDER BY r.student_id, r.course_name
                """,
                tuple(student_ids),
            ).fetchall()
        except Exception:
            _safe_rollback(conn)
            reg_rows = []
        for r in reg_rows or []:
            sid = str(_row_val(r, "student_id", 0) or "").strip()
            cn = str(_row_val(r, "course_name", 1) or "").strip()
            gsem = str(_row_val(r, "group_semester", 2) or "").strip()
            if not sid or not cn:
                continue
            in_term = bool(sem) and schedule_semester_matches_current_term(gsem, sem)
            if not in_term and sem and cn in plan_courses_by_student.get(sid, set()):
                in_term = True
            if not in_term:
                continue
            entry = base.setdefault(sid, {
                "registrations_count": 0,
                "registration_courses": [],
                "plan_id": None,
                "plan_status": None,
                "plan_courses_count": 0,
                "plan_courses": [],
            })
            entry["registrations_count"] += 1
            if len(entry["registration_courses"]) < 12:
                entry["registration_courses"].append(cn)

    return base


def _load_pending_review_items(
    conn, student_ids: list[str], semester: str, name_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    """خطط بانتظار الاعتماد وطلبات إضافة/إسقاط معلّقة لطلبة المشرف."""
    sem = (semester or "").strip()
    if not student_ids:
        return []
    items: list[dict[str, Any]] = []
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in student_ids)

    if table_exists(conn, "enrollment_plans"):
        try:
            plan_rows = cur.execute(
                f"""
                SELECT ep.id, ep.student_id, ep.status,
                       (SELECT COUNT(*) FROM enrollment_plan_items epi WHERE epi.plan_id = ep.id) AS course_count,
                       COALESCE(ep.updated_at, ep.created_at, '') AS updated_at
                FROM enrollment_plans ep
                WHERE ep.student_id IN ({placeholders})
                  AND ep.semester = ?
                  AND ep.status = 'Pending'
                ORDER BY ep.updated_at DESC, ep.id DESC
                """,
                (*student_ids, sem),
            ).fetchall()
        except Exception:
            _safe_rollback(conn)
            plan_rows = []
        for r in plan_rows or []:
            sid = str(_row_val(r, "student_id", 1) or "").strip()
            pid = _row_val(r, "id", 0)
            items.append({
                "kind": "enrollment_plan",
                "id": int(pid) if pid not in (None, "") else None,
                "student_id": sid,
                "student_name": name_by_id.get(sid, ""),
                "status": _row_val(r, "status", 2),
                "courses_count": int(_row_val(r, "course_count", 3) or 0),
                "updated_at": _row_val(r, "updated_at", 4) or "",
                "href": "/enrollment_plans",
                "label": "خطة تسجيل بانتظار الاعتماد",
            })

    if table_exists(conn, "registration_requests"):
        try:
            req_rows = cur.execute(
                f"""
                SELECT id, student_id, term, course_name, action, status, created_at
                FROM registration_requests
                WHERE student_id IN ({placeholders})
                  AND status = 'pending'
                  AND (? = '' OR term = ?)
                ORDER BY created_at DESC, id DESC
                """,
                (*student_ids, sem, sem),
            ).fetchall()
        except Exception:
            _safe_rollback(conn)
            req_rows = []
        action_ar = {"add": "إضافة", "drop": "إسقاط"}
        for r in req_rows or []:
            sid = str(_row_val(r, "student_id", 1) or "").strip()
            action = str(_row_val(r, "action", 4) or "").strip()
            items.append({
                "kind": "registration_request",
                "id": _row_val(r, "id", 0),
                "student_id": sid,
                "student_name": name_by_id.get(sid, ""),
                "term": _row_val(r, "term", 2) or "",
                "course_name": _row_val(r, "course_name", 3) or "",
                "action": action,
                "action_label": action_ar.get(action, action),
                "status": _row_val(r, "status", 5) or "",
                "created_at": _row_val(r, "created_at", 6) or "",
                "href": "/registration_requests_page",
                "label": f"طلب {action_ar.get(action, action)} مقرر",
            })

    return items


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
    student_ids = [str(s.get("student_id") or "").strip() for s in students if s.get("student_id")]
    name_by_id = {str(s.get("student_id") or "").strip(): s.get("student_name") or "" for s in students}
    failed_map = _failed_course_counts(conn, student_ids)
    academic_map = _load_semester_academic_by_student(conn, student_ids, sem)
    pending_review = _load_pending_review_items(conn, student_ids, sem, name_by_id)
    at_risk_threshold = 1
    for st in students:
        sid = (st.get("student_id") or "").strip()
        fc = int(failed_map.get(sid) or 0)
        st["failed_courses_count"] = fc
        st["at_risk"] = fc >= at_risk_threshold
        acad = academic_map.get(sid) or {}
        st["registrations_count"] = int(acad.get("registrations_count") or 0)
        st["registration_courses"] = acad.get("registration_courses") or []
        st["plan_id"] = acad.get("plan_id")
        st["plan_status"] = acad.get("plan_status")
        st["plan_courses_count"] = int(acad.get("plan_courses_count") or 0)
        st["plan_courses"] = acad.get("plan_courses") or []

    pending_count = int((quality.get("surveys") or {}).get("pending_count") or 0)
    report = quality.get("supervisor_report") or {}
    report_row = {}
    if iid_int:
        try:
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
        except Exception:
            _safe_rollback(conn)
    report_done = bool(report.get("submitted"))
    pending_review_count = len(pending_review)
    tasks = []
    if not iid_int:
        tasks.append({
            "level": "warning",
            "title": "ربط حساب الأستاذ",
            "message": "لم يُربط instructor_id — تواصل مع الإدارة.",
            "href": None,
        })
    if pending_review_count > 0:
        tasks.append({
            "level": "warning",
            "title": "طلبات تحتاج مراجعة",
            "message": f"لديك {pending_review_count} طلب/خطة بانتظار المراجعة أو الاعتماد لهذا الفصل.",
            "href": "/registration_requests_page",
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
        "pending_review": pending_review,
        "pending_review_count": pending_review_count,
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
