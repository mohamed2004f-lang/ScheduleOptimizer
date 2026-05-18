"""ضمان الجودة والاعتماد الأكاديمي — لوحة القيادة والتقارير."""

from __future__ import annotations

import datetime

from flask import Blueprint, jsonify, render_template, request, session

from backend.core.auth import login_required, role_required, current_supervisor_effective, _normalize_role
from backend.core.department_scope_policy import head_home_department_id, resolve_users_list_scope
from backend.core.auth import get_admin_department_scope_id
from backend.services.utilities import get_connection, pdf_response_from_html
from backend.services.evaluation_survey import (
    create_survey_question,
    delete_survey_question,
    list_survey_questions,
    reorder_survey_questions,
    update_survey_question,
)
from backend.services.quality_metrics import (
    compute_quality_metrics,
    list_critical_courses,
    save_metrics_snapshot,
    term_label_from_conn,
)

academic_quality_bp = Blueprint("academic_quality", __name__)


def _resolve_department_scope(conn) -> int | None:
    role = _normalize_role((session.get("user_role") or "").strip())
    if role in ("admin", "admin_main"):
        return get_admin_department_scope_id()
    if role == "head_of_department":
        mode, dept = resolve_users_list_scope(conn, session.get("user"))
        if mode == "department" and dept is not None:
            return int(dept)
        hid = head_home_department_id(conn, session.get("user"))
        return int(hid) if hid is not None else None
    return None


@academic_quality_bp.route("/dashboard")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def quality_dashboard():
    semester = (request.args.get("semester") or "").strip()
    with get_connection() as conn:
        dept_id = _resolve_department_scope(conn)
        metrics = compute_quality_metrics(
            conn,
            semester=semester or None,
            department_id=dept_id,
        )
        critical = list_critical_courses(conn, metrics["semester"], dept_id)
    return render_template(
        "academic_quality_dashboard.html",
        metrics=metrics,
        critical_courses=critical,
    )


@academic_quality_bp.route("/api/metrics")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def quality_metrics_api():
    semester = (request.args.get("semester") or "").strip() or None
    with get_connection() as conn:
        dept_id = _resolve_department_scope(conn)
        metrics = compute_quality_metrics(conn, semester=semester, department_id=dept_id)
    return jsonify({"status": "ok", "metrics": metrics})


@academic_quality_bp.route("/api/snapshot", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def save_snapshot():
    data = request.get_json(force=True) or {}
    semester = (data.get("semester") or "").strip() or None
    actor = (session.get("user") or "").strip()
    with get_connection() as conn:
        dept_id = _resolve_department_scope(conn)
        metrics = compute_quality_metrics(conn, semester=semester, department_id=dept_id)
        snap_id = save_metrics_snapshot(conn, metrics, actor=actor)
        conn.commit()
    return jsonify({"status": "ok", "snapshot_id": snap_id, "metrics": metrics})


@academic_quality_bp.route("/api/institutional_inputs", methods=["GET", "POST"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def institutional_inputs():
    with get_connection() as conn:
        dept_id = _resolve_department_scope(conn)
        sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
        cur = conn.cursor()
        if request.method == "GET":
            row = cur.execute(
                """
                SELECT faculty_qualifications_percent, infrastructure_rating, notes
                FROM quality_institutional_inputs
                WHERE semester = ? AND (
                    (? IS NULL AND department_id IS NULL) OR department_id = ?
                )
                LIMIT 1
                """,
                (sem, dept_id, dept_id),
            ).fetchone()
            if not row:
                return jsonify({"status": "ok", "semester": sem, "inputs": {}})
            return jsonify(
                {
                    "status": "ok",
                    "semester": sem,
                    "inputs": {
                        "faculty_qualifications_percent": row[0],
                        "infrastructure_rating": row[1],
                        "notes": row[2] or "",
                    },
                }
            )
        data = request.get_json(force=True) or {}
        sem = (data.get("semester") or sem).strip()
        fq = data.get("faculty_qualifications_percent")
        infra = data.get("infrastructure_rating")
        notes = (data.get("notes") or "").strip()
        actor = (session.get("user") or "").strip()
        now = datetime.datetime.utcnow().isoformat()
        if dept_id is None:
            cur.execute(
                """
                DELETE FROM quality_institutional_inputs
                WHERE semester = ? AND department_id IS NULL
                """,
                (sem,),
            )
            cur.execute(
                """
                INSERT INTO quality_institutional_inputs
                    (semester, department_id, faculty_qualifications_percent, infrastructure_rating, notes, updated_at, updated_by)
                VALUES (?, NULL, ?, ?, ?, ?, ?)
                """,
                (sem, fq, infra, notes, now, actor),
            )
        else:
            cur.execute(
                """
                INSERT INTO quality_institutional_inputs
                    (semester, department_id, faculty_qualifications_percent, infrastructure_rating, notes, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (semester, department_id) DO UPDATE SET
                    faculty_qualifications_percent = excluded.faculty_qualifications_percent,
                    infrastructure_rating = excluded.infrastructure_rating,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (sem, int(dept_id), fq, infra, notes, now, actor),
            )
        conn.commit()
    return jsonify({"status": "ok"})


@academic_quality_bp.route("/supervisor_report", methods=["GET", "POST"])
@login_required
def supervisor_quality_report():
    if not current_supervisor_effective():
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    instructor_id = session.get("instructor_id")
    if not instructor_id:
        return jsonify({"status": "error", "message": "لا يوجد ربط بعضو هيئة التدريس"}), 400
    iid = int(instructor_id)
    with get_connection() as conn:
        sem = term_label_from_conn(conn)
        cur = conn.cursor()
        if request.method == "GET":
            row = cur.execute(
                """
                SELECT at_risk_students_count, intervention_actions, success_rate, submitted_at
                FROM supervisor_quality_reports
                WHERE supervisor_instructor_id = ? AND semester = ?
                LIMIT 1
                """,
                (iid, sem),
            ).fetchone()
            if not row:
                return jsonify({"status": "ok", "semester": sem, "report": {}})
            return jsonify(
                {
                    "status": "ok",
                    "semester": sem,
                    "report": {
                        "at_risk_students_count": row[0],
                        "intervention_actions": row[1] or "",
                        "success_rate": row[2],
                        "submitted_at": row[3],
                    },
                }
            )
        data = request.get_json(force=True) or {}
        sem = (data.get("semester") or sem).strip()
        try:
            at_risk = int(data.get("at_risk_students_count") or 0)
        except (TypeError, ValueError):
            at_risk = 0
        interventions = (data.get("intervention_actions") or "").strip()
        try:
            success_rate = float(data.get("success_rate")) if data.get("success_rate") not in (None, "") else None
        except (TypeError, ValueError):
            success_rate = None
        actor = (session.get("user") or "").strip()
        now = datetime.datetime.utcnow().isoformat()
        cur.execute(
            """
            INSERT INTO supervisor_quality_reports
                (supervisor_instructor_id, semester, at_risk_students_count, intervention_actions, success_rate, submitted_by, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (supervisor_instructor_id, semester) DO UPDATE SET
                at_risk_students_count = excluded.at_risk_students_count,
                intervention_actions = excluded.intervention_actions,
                success_rate = excluded.success_rate,
                submitted_by = excluded.submitted_by,
                submitted_at = excluded.submitted_at
            """,
            (iid, sem, at_risk, interventions, success_rate, actor, now),
        )
        conn.commit()
    return jsonify({"status": "ok"})


@academic_quality_bp.route("/export/program")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def export_program_report():
    """تصدير HTML للطباعة — تقرير الاعتماد البرامجي."""
    with get_connection() as conn:
        dept_id = _resolve_department_scope(conn)
        metrics = compute_quality_metrics(conn, department_id=dept_id)
        critical = list_critical_courses(conn, metrics["semester"], dept_id)
    return render_template(
        "academic_quality_export_program.html",
        metrics=metrics,
        critical_courses=critical,
        title="تقرير الاعتماد البرامجي",
    )


@academic_quality_bp.route("/export/program.pdf")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def export_program_report_pdf():
    with get_connection() as conn:
        dept_id = _resolve_department_scope(conn)
        metrics = compute_quality_metrics(conn, department_id=dept_id)
        critical = list_critical_courses(conn, metrics["semester"], dept_id)
    html = render_template(
        "academic_quality_export_program.html",
        metrics=metrics,
        critical_courses=critical,
        title="تقرير الاعتماد البرامجي",
        for_pdf=True,
    )
    return pdf_response_from_html(html, filename_prefix="program_accreditation")


@academic_quality_bp.route("/export/institutional")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def export_institutional_report():
    with get_connection() as conn:
        dept_id = _resolve_department_scope(conn)
        metrics = compute_quality_metrics(conn, department_id=dept_id)
    return render_template(
        "academic_quality_export_institutional.html",
        metrics=metrics,
        title="تقرير الاعتماد المؤسسي",
    )


@academic_quality_bp.route("/export/institutional.pdf")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def export_institutional_report_pdf():
    with get_connection() as conn:
        dept_id = _resolve_department_scope(conn)
        metrics = compute_quality_metrics(conn, department_id=dept_id)
    html = render_template(
        "academic_quality_export_institutional.html",
        metrics=metrics,
        title="تقرير الاعتماد المؤسسي",
        for_pdf=True,
    )
    return pdf_response_from_html(html, filename_prefix="institutional_accreditation")


@academic_quality_bp.route("/supervisor_report_page")
@login_required
def supervisor_report_page():
    if not current_supervisor_effective():
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    return render_template("supervisor_quality_report.html")


@academic_quality_bp.route("/survey_admin")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def survey_admin_page():
    with get_connection() as conn:
        questions = list_survey_questions(conn)
    return render_template("evaluation_survey_admin.html", questions=questions)


@academic_quality_bp.route("/api/survey_questions", methods=["GET", "POST"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def survey_questions_api():
    with get_connection() as conn:
        if request.method == "GET":
            return jsonify({"status": "ok", "questions": list_survey_questions(conn)})
        data = request.get_json(force=True) or {}
        label = (data.get("label_ar") or "").strip()
        try:
            q = create_survey_question(conn, label)
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
    return jsonify({"status": "ok", "question": q})


@academic_quality_bp.route("/api/survey_questions/<int:question_id>", methods=["PUT", "DELETE"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def survey_question_item_api(question_id: int):
    with get_connection() as conn:
        if request.method == "DELETE":
            ok, msg = delete_survey_question(conn, question_id)
            if not ok:
                return jsonify({"status": "error", "message": msg}), 409
            return jsonify({"status": "ok"})
        data = request.get_json(force=True) or {}
        label = data.get("label_ar")
        is_active = data.get("is_active")
        if is_active is not None:
            try:
                is_active = int(is_active)
            except (TypeError, ValueError):
                is_active = None
        try:
            q = update_survey_question(
                conn,
                question_id,
                label_ar=label if label is not None else None,
                is_active=is_active,
            )
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        if not q:
            return jsonify({"status": "error", "message": "البند غير موجود"}), 404
    return jsonify({"status": "ok", "question": q})


@academic_quality_bp.route("/api/survey_questions/reorder", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def survey_questions_reorder_api():
    data = request.get_json(force=True) or {}
    order = data.get("order") or data.get("ordered_ids") or []
    if not isinstance(order, list):
        return jsonify({"status": "error", "message": "صيغة الترتيب غير صالحة"}), 400
    with get_connection() as conn:
        try:
            questions = reorder_survey_questions(conn, order)
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
    return jsonify({"status": "ok", "questions": questions})
