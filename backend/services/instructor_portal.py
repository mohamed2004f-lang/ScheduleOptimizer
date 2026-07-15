"""بوابة الأستاذ: ضمان الجودة (هوية + استبيانات)."""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request, session

from backend.core.auth import (
    SESSION_ACTIVE_MODE,
    _normalize_role,
    is_supervisor_effective_session,
    login_required,
)
from backend.services.multi_surveys import list_pending_for_user, survey_respondent_role
from backend.services.student_portal import (
    _build_college_identity,
    _current_term_label,
    _department_identity,
)
from backend.services.survey_platform_routes import (
    _count_supervisor_templates,
    _count_templates_for_respondent,
    _enrich_pending_surveys,
    _session_active_mode,
    _session_payload,
    build_survey_hub_status,
)
from backend.services import utilities as db_util

logger = logging.getLogger(__name__)

instructor_portal_bp = Blueprint("instructor_portal", __name__)


def instructor_portal_session_allowed() -> bool:
    """أستاذ أو رئيس قسم في وضع التدريس (نفس منطق مقرراتي)."""
    role = _normalize_role((session.get("user_role") or "").strip())
    try:
        db_sup = int(session.get("is_supervisor") or 0) == 1
    except (TypeError, ValueError):
        db_sup = False
    if role == "head_of_department":
        active_m = (session.get(SESSION_ACTIVE_MODE) or "head").strip().lower()
    else:
        active_m = (session.get(SESSION_ACTIVE_MODE) or "instructor").strip().lower()
    has_instructor = bool(session.get("instructor_id"))
    return has_instructor and (
        (role == "instructor" and (not db_sup or active_m == "instructor"))
        or (role == "head_of_department" and active_m == "instructor")
    )


def _instructor_profile(conn, instructor_id: int) -> dict | None:
    cur = conn.cursor()
    try:
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
    except Exception:
        return None
    if not row:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    return {
        "id": row[0],
        "name": row[1] or "",
        "department_id": row[2],
        "department_name": row[3] or "",
    }


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
                "icon": intro.get("icon") or "",
                "subtitle_ar": intro.get("subtitle_ar") or "",
                "about_ar": intro.get("about_ar") or "",
                "duration_hint": intro.get("duration_hint") or "",
            },
        })
    return out


def _resolve_instructor_department_id(conn, role: str, session_data: dict) -> int | None:
    """استنتاج قسم الأستاذ من بيانات الجلسة (بدون الاعتماد على session مباشرة)."""
    role_n = _normalize_role((role or "").strip())
    uname = (session_data.get("user") or session_data.get("username") or "").strip()
    cur = conn.cursor()
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
    iid = session_data.get("instructor_id")
    if iid and role_n in ("instructor", "head_of_department", "supervisor"):
        try:
            iid_i = int(iid)
        except (TypeError, ValueError):
            iid_i = 0
        if iid_i:
            try:
                inst = cur.execute(
                    "SELECT department_id FROM instructors WHERE id = ? LIMIT 1",
                    (iid_i,),
                ).fetchone()
                if inst and inst[0] not in (None, ""):
                    return int(inst[0])
            except Exception:
                pass
    return None


def build_instructor_quality_context(
    conn,
    *,
    role: str,
    session_data: dict,
    active_mode: str,
    semester: str | None = None,
) -> dict[str, Any]:
    """هوية الكلية/القسم + ملخص استبيانات الأستاذ."""
    _, _, term_label = _current_term_label(conn)
    sem = (semester or "").strip() or term_label
    dept_id = _resolve_instructor_department_id(conn, role, session_data)
    iid = session_data.get("instructor_id")
    try:
        iid_int = int(iid) if iid not in (None, "") else 0
    except (TypeError, ValueError):
        iid_int = 0

    profile = _instructor_profile(conn, iid_int) if iid_int else None
    if profile and profile.get("department_id") not in (None, "") and dept_id is None:
        try:
            dept_id = int(profile["department_id"])
        except (TypeError, ValueError):
            pass

    college = _build_college_identity(conn)
    department = _department_identity(conn, dept_id)

    is_supervisor_db = session_data.get("is_supervisor")
    supervisor_effective = is_supervisor_effective_session(role, is_supervisor_db, active_mode)
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

    supervisor_template_count = _count_supervisor_templates(conn) if supervisor_effective else 0
    dept_missing = supervisor_effective and dept_id is None and supervisor_template_count > 0
    hub_status = build_survey_hub_status(
        conn,
        role=role,
        session_data=session_data,
        semester=sem,
        department_id=dept_id,
        active_mode=active_mode,
        pending=pending,
        supervisor_effective=supervisor_effective,
        supervisor_template_count=supervisor_template_count,
        dept_missing=dept_missing,
    )

    template_count = _count_templates_for_respondent(conn, eff)
    pending_count = len(pending)

    return {
        "instructor_id": iid_int or None,
        "instructor_name": (profile or {}).get("name") or "",
        "department_id": dept_id,
        "department_name": (profile or {}).get("department_name") or (department or {}).get("name_ar") or "",
        "term_label": sem,
        "respondent_role": eff,
        "supervisor_effective": supervisor_effective,
        "college": college,
        "department": department,
        "surveys": {
            "pending": _serialize_pending(pending),
            "pending_count": pending_count,
            "template_count": template_count,
            "all_done": pending_count == 0 and template_count > 0,
            "hub_status": hub_status,
            "fill_hub_url": "/academic_quality/surveys",
        },
        "links": {
            "surveys_fill": "/academic_quality/surveys",
            "ilo_catalog": "/academic_quality/ilo/catalog",
            "glossary": "/academic_quality/glossary",
            "my_courses": "/my_courses",
        },
    }


def _instructor_forbidden():
    return jsonify({"status": "error", "message": "غير مصرح — هذه الصفحة لعضو هيئة التدريس فقط"}), 403


@instructor_portal_bp.route("/quality_context", methods=["GET"])
@login_required
def api_instructor_quality_context():
    if not instructor_portal_session_allowed():
        return _instructor_forbidden()
    role = _normalize_role((session.get("user_role") or "").strip())
    active_mode = _session_active_mode(role)
    sem = (request.args.get("semester") or "").strip()
    with db_util.get_connection() as conn:
        data = build_instructor_quality_context(
            conn,
            role=role,
            session_data=_session_payload(),
            active_mode=active_mode,
            semester=sem or None,
        )
    return jsonify({"status": "ok", **data})


@instructor_portal_bp.route("/me", methods=["GET"])
@login_required
def api_instructor_me():
    if not instructor_portal_session_allowed():
        return _instructor_forbidden()
    role = _normalize_role((session.get("user_role") or "").strip())
    iid = session.get("instructor_id")
    with db_util.get_connection() as conn:
        profile = _instructor_profile(conn, int(iid)) if iid else None
        _, _, term_label = _current_term_label(conn)
    if not profile:
        return jsonify({"status": "error", "message": "لم يُعثر على عضو هيئة التدريس"}), 404
    return jsonify({
        "status": "ok",
        "instructor_id": profile.get("id"),
        "instructor_name": profile.get("name") or "",
        "department_id": profile.get("department_id"),
        "department_name": profile.get("department_name") or "",
        "role": role,
        "term_label": term_label,
    })
