"""بوابة الطالب: me، portal_summary، academic_progress، وصفحات مرتبطة."""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, render_template, request, session

from backend.core.auth import login_required, role_required, _normalize_role
from backend.core.college_identity_schema import ensure_college_identity_schema
from backend.database.database import fetch_table_columns, table_exists
from backend.services.college_identity_portal import _active_identity, _strategic_goals_tree, program_profile_payload
from backend.services.course_evaluations import list_pending_course_evaluations
from backend.services.multi_surveys import list_pending_for_user
from backend.services.survey_identity_context import sanitize_survey_display_text
from backend.services.utilities import (
    get_connection,
    get_current_term,
    get_exam_schedule_published_at,
    get_schedule_published_at,
    SEMESTER_LABEL,
)
from backend.services.grades import _load_transcript_data
from backend.services.students import normalize_sid
from backend.services.quality_metrics import term_label_from_conn

logger = logging.getLogger(__name__)

student_portal_bp = Blueprint("student_portal", __name__)


def session_student_id(*, allow_staff_view: str | None = None) -> str | None:
    """معرّف الطالب من الجلسة؛ للطالب يُ ignor معامل URL."""
    role = _normalize_role((session.get("user_role") or "").strip())
    if role == "student":
        return normalize_sid(session.get("student_id") or session.get("user"))
    if allow_staff_view:
        return normalize_sid(allow_staff_view)
    return None


def _student_row(conn, sid: str) -> dict | None:
    cur = conn.cursor()
    cols = {c.lower() for c in fetch_table_columns(conn, "students")}
    extra = ""
    if "department_id" in cols:
        extra += ", s.department_id"
    if "current_program_id" in cols:
        extra += ", s.current_program_id"
    if "admission_program_id" in cols:
        extra += ", s.admission_program_id"
    row = cur.execute(
        f"""
        SELECT s.student_id, COALESCE(s.student_name,'') AS student_name,
               COALESCE(s.university_number,'') AS university_number
               {extra}
        FROM students s WHERE s.student_id = ? LIMIT 1
        """,
        (sid,),
    ).fetchone()
    if not row:
        return None
    d = dict(row) if hasattr(row, "keys") else {
        "student_id": row[0],
        "student_name": row[1] or "",
        "university_number": row[2] or "",
    }
    dept_id = d.get("department_id")
    prog_id = d.get("current_program_id") or d.get("admission_program_id")
    dept_name = ""
    prog_name = ""
    if dept_id not in (None, ""):
        try:
            dr = cur.execute(
                "SELECT COALESCE(name_ar, code, '') FROM departments WHERE id = ? LIMIT 1",
                (int(dept_id),),
            ).fetchone()
            dept_name = (dr[0] if dr else "") or ""
        except Exception:
            pass
    if prog_id not in (None, ""):
        try:
            pr = cur.execute(
                "SELECT COALESCE(name_ar, code, '') FROM programs WHERE id = ? LIMIT 1",
                (int(prog_id),),
            ).fetchone()
            prog_name = (pr[0] if pr else "") or ""
        except Exception:
            pass
    d["department_name"] = dept_name
    d["program_name"] = prog_name
    d["program_id"] = int(prog_id) if prog_id not in (None, "") else None
    d["department_id"] = int(dept_id) if dept_id not in (None, "") else None
    return d


def _current_term_label(conn) -> tuple[str, str, str]:
    term_name, term_year = get_current_term(conn=conn)
    label = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip() or SEMESTER_LABEL
    return term_name or "", term_year or "", label


def _registrations_summary(conn, sid: str, term_label: str) -> dict[str, Any]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT r.course_name, COALESCE(c.course_code,'') AS course_code,
               COALESCE(c.units, 0) AS units
        FROM registrations r
        LEFT JOIN courses c ON c.course_name = r.course_name
        WHERE r.student_id = ?
        ORDER BY r.course_name
        """,
        (sid,),
    ).fetchall()
    courses = []
    units = 0
    for r in rows or []:
        cn = r[0] if not hasattr(r, "keys") else r["course_name"]
        cc = r[1] if not hasattr(r, "keys") else r["course_code"]
        u = int((r[2] if not hasattr(r, "keys") else r["units"]) or 0)
        units += u
        courses.append({"course_name": cn, "course_code": cc, "units": u})
    return {
        "count": len(courses),
        "units": units,
        "courses": courses[:20],
    }


def _enrollment_plan_status(conn, sid: str, term_label: str) -> dict[str, Any]:
    cur = conn.cursor()
    try:
        row = cur.execute(
            """
            SELECT id, status, COALESCE(rejection_reason,'') AS rejection_reason
            FROM enrollment_plans
            WHERE student_id = ? AND semester = ?
            ORDER BY id DESC LIMIT 1
            """,
            (sid, term_label),
        ).fetchone()
    except Exception:
        return {"status": None, "rejection_reason": ""}
    if not row:
        return {"status": None, "rejection_reason": ""}
    if hasattr(row, "keys"):
        return {"status": row["status"], "rejection_reason": row["rejection_reason"] or ""}
    return {"status": row[1], "rejection_reason": (row[2] or "") if len(row) > 2 else ""}


def _schedule_conflicts(conn, sid: str) -> list[dict]:
    if not table_exists(conn, "conflict_report"):
        return []
    cur = conn.cursor()
    try:
        rows = cur.execute(
            "SELECT student_id, day, time, conflicting_sections FROM conflict_report WHERE student_id = ?",
            (sid,),
        ).fetchall()
    except Exception:
        return []
    out = []
    for r in rows or []:
        if hasattr(r, "keys"):
            out.append(dict(r))
        else:
            out.append({
                "student_id": r[0],
                "day": r[1],
                "time": r[2],
                "conflicting_sections": r[3],
            })
    return out


def _announcements_preview(conn, sid: str, limit: int = 5) -> tuple[int, list]:
    from backend.database.database import schedule_pk_column

    pk = schedule_pk_column(conn)
    cur = conn.cursor()
    try:
        rows = cur.execute(
            f"""
            SELECT a.id, COALESCE(s.course_name,'') AS course_name,
                   COALESCE(a.title,'') AS title, COALESCE(a.created_at,'') AS created_at
            FROM faculty_course_announcements a
            JOIN schedule s ON s.{pk} = a.section_id
            JOIN registrations r ON LOWER(TRIM(r.course_name)) = LOWER(TRIM(s.course_name))
            WHERE r.student_id = ? AND COALESCE(a.published_to_students, 1) = 1
            ORDER BY a.id DESC LIMIT ?
            """,
            (sid, int(limit)),
        ).fetchall()
    except Exception:
        return 0, []
    items = []
    for r in rows or []:
        items.append({
            "id": int(r[0]),
            "course_name": r[1] or "",
            "title": r[2] or "",
            "created_at": r[3] or "",
        })
    try:
        cnt_row = cur.execute(
            f"""
            SELECT COUNT(*) FROM faculty_course_announcements a
            JOIN schedule s ON s.{pk} = a.section_id
            JOIN registrations r ON LOWER(TRIM(r.course_name)) = LOWER(TRIM(s.course_name))
            WHERE r.student_id = ? AND COALESCE(a.published_to_students, 1) = 1
            """,
            (sid,),
        ).fetchone()
        total = int(cnt_row[0]) if cnt_row else len(items)
    except Exception:
        total = len(items)
    return total, items


def _upcoming_exams_count(conn, sid: str) -> int:
    cur = conn.cursor()
    try:
        row = cur.execute(
            """
            SELECT COUNT(DISTINCT e.id)
            FROM exams e
            INNER JOIN registrations r ON LOWER(TRIM(r.course_name)) = LOWER(TRIM(e.course_name))
            WHERE r.student_id = ? AND e.exam_type IN ('midterm','final')
            """,
            (sid,),
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def build_portal_summary(conn, sid: str) -> dict[str, Any]:
    stu = _student_row(conn, sid) or {}
    term_name, term_year, term_label = _current_term_label(conn)
    regs = _registrations_summary(conn, sid, term_label)
    plan = _enrollment_plan_status(conn, sid, term_label)
    gpa = None
    completed_units = None
    try:
        tr = _load_transcript_data(sid)
        if tr:
            gpa = tr.get("cumulative_gpa")
            completed_units = tr.get("completed_units")
    except Exception:
        pass
    sem = term_label_from_conn(conn)
    eval_pending = list_pending_course_evaluations(conn, sid, semester=sem)
    surveys_pending = list_pending_for_user(
        conn,
        user_role="student",
        session_data=dict(session),
        semester=sem,
    )
    conflicts = _schedule_conflicts(conn, sid)
    ann_total, ann_recent = _announcements_preview(conn, sid)
    exams_count = _upcoming_exams_count(conn, sid)
    published_at = get_schedule_published_at(conn)
    exam_pub = get_exam_schedule_published_at("midterm", conn=conn) or get_exam_schedule_published_at("final", conn=conn)

    action_items: list[dict] = []
    for ev in eval_pending[:5]:
        action_items.append({
            "type": "course_eval_pending",
            "tab": "quality",
            "focus": "evaluations",
            "course": ev.get("course_name") or "",
            "message": ev.get("title_ar") or "تقييم مقرر معلّق",
            "href": ev.get("fill_url") or "/students/evaluations/",
        })
    for sv in surveys_pending[:5]:
        action_items.append({
            "type": "survey_pending",
            "tab": "quality",
            "focus": "surveys",
            "course": "",
            "message": sv.get("title_ar") or "استبيان معلّق",
            "href": sv.get("fill_url") or "/academic_quality/surveys",
        })
    if plan.get("status") == "Rejected":
        action_items.append({
            "type": "plan_rejected",
            "tab": "registrations",
            "focus": "plan",
            "message": "خطة التسجيل مرفوضة — راجع السبب وعدّلها",
            "href": "/my_registrations?focus=plan",
        })
    elif plan.get("status") == "Draft":
        action_items.append({
            "type": "plan_draft",
            "tab": "registrations",
            "focus": "plan",
            "message": "لديك مسودة خطة تسجيل — أكملها وأرسلها",
            "href": "/my_registrations?focus=plan",
        })
    for c in conflicts[:3]:
        action_items.append({
            "type": "schedule_conflict",
            "tab": "registrations",
            "focus": "conflicts",
            "message": f"تعارض جدول: {c.get('day')} {c.get('time')}",
            "href": "/my_registrations?tab=conflicts",
        })
    if stu.get("program_id") or stu.get("department_id"):
        action_items.append({
            "type": "identity_read",
            "tab": "quality",
            "focus": "identity",
            "message": "اطلع على رؤية كليتك وقسمك وبرنامجك",
            "href": "/academic_quality/student/identity",
        })

    return {
        "student_id": sid,
        "student_name": stu.get("student_name") or sid,
        "university_number": stu.get("university_number") or "",
        "department_id": stu.get("department_id"),
        "department_name": stu.get("department_name") or "",
        "program_id": stu.get("program_id"),
        "program_name": stu.get("program_name") or "",
        "term_label": term_label,
        "term_name": term_name,
        "term_year": term_year,
        "registrations_count": regs["count"],
        "units_registered": regs["units"],
        "registrations_preview": regs["courses"],
        "gpa": gpa,
        "completed_units": completed_units,
        "enrollment_plan_status": plan.get("status"),
        "enrollment_plan_rejection": plan.get("rejection_reason") or "",
        "quality_counts": {
            "evaluations_pending": len(eval_pending),
            "surveys_pending": len(surveys_pending),
            "identity_available": bool(stu.get("program_id") or stu.get("department_id")),
        },
        "announcements_total": ann_total,
        "announcements_recent": ann_recent,
        "exams_upcoming": exams_count,
        "schedule_published": published_at is not None,
        "exam_schedule_published": exam_pub is not None,
        "schedule_conflicts": conflicts,
        "action_items": action_items,
    }


def _goals_for_display(goals: list) -> list[dict]:
    out = []
    for g in goals or []:
        if isinstance(g, dict):
            title = sanitize_survey_display_text(g.get("title_ar") or "")
            desc = sanitize_survey_display_text(g.get("description") or "")
            if title or desc:
                out.append({"title_ar": title, "description_ar": desc, "code": g.get("code") or ""})
    return out


def _department_identity(conn, dept_id: int | None) -> dict | None:
    if dept_id is None:
        return None
    ensure_college_identity_schema(conn)
    cur = conn.cursor()
    cols = {c.lower() for c in fetch_table_columns(conn, "departments")}
    intro = mission = vision = ""
    if "intro_ar" in cols:
        row = cur.execute(
            """
            SELECT COALESCE(intro_ar,''), COALESCE(mission_ar,''), COALESCE(vision_ar,''),
                   COALESCE(name_ar, code, '') AS name_ar
            FROM departments WHERE id = ? LIMIT 1
            """,
            (int(dept_id),),
        ).fetchone()
        if row:
            if hasattr(row, "keys"):
                intro, mission, vision = row["intro_ar"], row["mission_ar"], row["vision_ar"]
                name = row["name_ar"]
            else:
                intro, mission, vision, name = row[0], row[1], row[2], row[3]
        else:
            return None
    else:
        row = cur.execute(
            "SELECT COALESCE(name_ar, code, '') FROM departments WHERE id = ? LIMIT 1",
            (int(dept_id),),
        ).fetchone()
        name = (row[0] if row else "") or ""
    goals: list[dict] = []
    if table_exists(conn, "department_goals"):
        try:
            gr = cur.execute(
                """
                SELECT code, title_ar, COALESCE(description,'') AS description
                FROM department_goals
                WHERE department_id = ? AND COALESCE(is_active,1)=1
                ORDER BY sort_order, code
                """,
                (int(dept_id),),
            ).fetchall()
            goals = _goals_for_display([dict(x) if hasattr(x, "keys") else {
                "code": x[0], "title_ar": x[1], "description": x[2],
            } for x in gr or []])
        except Exception:
            pass
    has_profile = bool((mission or "").strip() or (vision or "").strip() or goals)
    return {
        "department_id": int(dept_id),
        "name_ar": name,
        "intro_ar": sanitize_survey_display_text(intro),
        "mission_ar": (mission or "").strip(),
        "vision_ar": (vision or "").strip(),
        "goals": goals,
        "has_profile": has_profile,
    }


def build_identity_context(conn, sid: str) -> dict[str, Any]:
    stu = _student_row(conn, sid) or {}
    ensure_college_identity_schema(conn)
    cur = conn.cursor()
    identity = _active_identity(cur)
    goals_tree = _strategic_goals_tree(cur)
    college_goals = []
    for root in goals_tree:
        college_goals.append({
            "title_ar": sanitize_survey_display_text(root.get("title_ar") or ""),
            "description_ar": sanitize_survey_display_text(root.get("description") or ""),
            "children": [
                {
                    "title_ar": sanitize_survey_display_text(ch.get("title_ar") or ""),
                    "description_ar": sanitize_survey_display_text(ch.get("description") or ""),
                }
                for ch in (root.get("children") or [])
            ],
        })
    core_values = []
    for v in identity.get("values") or []:
        if isinstance(v, dict):
            core_values.append({
                "title_ar": sanitize_survey_display_text(v.get("title_ar") or ""),
                "description_ar": sanitize_survey_display_text(v.get("description") or ""),
            })
    college = {
        "intro_ar": sanitize_survey_display_text(identity.get("intro_ar") or ""),
        "mission_ar": (identity.get("mission_ar") or "").strip(),
        "vision_ar": (identity.get("vision_ar") or "").strip(),
        "strategic_plan_summary_ar": sanitize_survey_display_text(
            identity.get("strategic_plan_summary_ar") or identity.get("intro_ar") or ""
        ),
        "core_values": core_values,
        "strategic_goals": college_goals,
    }
    program = None
    pid = stu.get("program_id")
    if pid:
        pp = program_profile_payload(conn, int(pid))
        if pp:
            program = {
                "program_id": int(pid),
                "name_ar": pp.get("program", {}).get("name_ar") or stu.get("program_name") or "",
                "code": pp.get("program", {}).get("code") or "",
                "department_name": pp.get("program", {}).get("department_name") or "",
                "intro_ar": sanitize_survey_display_text(pp.get("program", {}).get("intro_ar") or ""),
                "mission_ar": (pp.get("program", {}).get("mission_ar") or "").strip(),
                "vision_ar": (pp.get("program", {}).get("vision_ar") or "").strip(),
                "goals": _goals_for_display(pp.get("goals") or []),
            }
    department = _department_identity(conn, stu.get("department_id"))
    return {
        "student_name": stu.get("student_name") or sid,
        "department_name": stu.get("department_name") or "",
        "program_name": stu.get("program_name") or "",
        "college": college,
        "department": department,
        "program": program,
        "links": {
            "learning_outcomes": "/academic_quality/ilo/student/learning-outcomes",
            "surveys": "/academic_quality/surveys",
            "course_evaluations": "/students/evaluations/",
            "academic_progress": "/academic_quality/student/progress",
            "portal": "/my_portal",
        },
    }


def build_academic_progress(conn, sid: str) -> dict[str, Any]:
    from backend.services.learning_outcomes import student_learning_outcomes_payload
    from backend.core.pathway_progress import compute_pathway_progress

    lo = student_learning_outcomes_payload(conn, sid)
    cur = conn.cursor()
    pathway = compute_pathway_progress(cur, sid)
    tr = _load_transcript_data(sid) or {}
    return {
        "glo_summary": lo.get("glo_summary") or [],
        "courses": lo.get("courses") or [],
        "pathway": pathway if pathway.get("status") != "error" else None,
        "gpa": tr.get("cumulative_gpa"),
        "completed_units": tr.get("completed_units"),
    }


def _student_forbidden():
    return jsonify({"status": "error", "message": "غير مصرح"}), 403


@student_portal_bp.route("/me", methods=["GET"])
@login_required
@role_required("student")
def api_student_me():
    sid = session_student_id()
    if not sid:
        return _student_forbidden()
    with get_connection() as conn:
        stu = _student_row(conn, sid)
        if not stu:
            return jsonify({"status": "error", "message": "لم يُعثر على الطالب"}), 404
        _, _, term_label = _current_term_label(conn)
        regs = _registrations_summary(conn, sid, term_label)
    return jsonify({
        "status": "ok",
        **stu,
        "term_label": term_label,
        "registrations_count": regs["count"],
        "units_registered": regs["units"],
    })


@student_portal_bp.route("/portal_summary", methods=["GET"])
@login_required
@role_required("student")
def api_portal_summary():
    sid = session_student_id()
    if not sid:
        return _student_forbidden()
    with get_connection() as conn:
        return jsonify({"status": "ok", **build_portal_summary(conn, sid)})


@student_portal_bp.route("/academic_progress", methods=["GET"])
@login_required
@role_required("student")
def api_academic_progress():
    sid = session_student_id()
    if not sid:
        return _student_forbidden()
    with get_connection() as conn:
        return jsonify({"status": "ok", **build_academic_progress(conn, sid)})


@student_portal_bp.route("/identity_context", methods=["GET"])
@login_required
@role_required("student")
def api_identity_context():
    sid = session_student_id()
    if not sid:
        return _student_forbidden()
    with get_connection() as conn:
        return jsonify({"status": "ok", **build_identity_context(conn, sid)})
