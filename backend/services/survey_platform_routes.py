"""مسارات منصة الاستبيانات (و-0 → و-5)."""

from __future__ import annotations

from flask import jsonify, redirect, render_template, request, session, url_for

from backend.core.auth import (
    SESSION_ACTIVE_MODE,
    _normalize_role,
    get_admin_department_scope_id,
    is_supervisor_effective_session,
    login_required,
    role_required,
)
from backend.core.department_scope_policy import head_home_department_id, resolve_users_list_scope
from backend.core.survey_platform import RESPONDENT_ROLE_LABELS, ROLE_SURVEY_FILL_GUIDE
from backend.services.multi_surveys import (
    aggregate_template,
    get_template_by_code,
    list_pending_for_respondent_role,
    list_pending_for_user,
    list_template_questions,
    list_templates,
    parse_answers_payload,
    submit_survey_response,
    survey_metrics_for_quality,
    survey_respondent_role,
    _resolve_subject,
)
from backend.services.evaluation_survey import likert_labels_ar
from backend.services.quality_metrics import term_label_from_conn
from backend.services.utilities import get_connection, excel_response_from_df
import pandas as pd


def _session_payload() -> dict:
    return {
        "user": session.get("user"),
        "user_role": session.get("user_role"),
        "student_id": session.get("student_id"),
        "instructor_id": session.get("instructor_id"),
    }


def _user_department_id(conn) -> int | None:
    role = _normalize_role((session.get("user_role") or "").strip())
    if role in ("admin", "admin_main"):
        return get_admin_department_scope_id()
    if role == "head_of_department":
        hid = head_home_department_id(conn, session.get("user"))
        if hid is not None:
            return int(hid)
        _mode, dept = resolve_users_list_scope(conn, session.get("user"))
        if dept is not None:
            return int(dept)
    cur = conn.cursor()
    row = cur.execute(
        "SELECT department_id FROM users WHERE lower(username)=lower(?) LIMIT 1",
        ((session.get("user") or "").strip(),),
    ).fetchone()
    if row and row[0] is not None:
        try:
            return int(row[0])
        except (TypeError, ValueError):
            pass
    iid = session.get("instructor_id")
    if iid and role in ("instructor", "head_of_department", "supervisor"):
        try:
            iid_i = int(iid)
        except (TypeError, ValueError):
            iid_i = 0
        if iid_i:
            inst = cur.execute(
                "SELECT department_id FROM instructors WHERE id = ? LIMIT 1",
                (iid_i,),
            ).fetchone()
            if inst and inst[0] is not None:
                return int(inst[0])
    return None


def _session_active_mode(role: str) -> str:
    am = (session.get(SESSION_ACTIVE_MODE) or "").strip().lower()
    if role == "head_of_department":
        return am if am in ("head", "instructor", "supervisor") else "head"
    if role == "instructor":
        return am if am in ("instructor", "supervisor") else "instructor"
    return am


def _active_mode_label_ar(role: str, active_mode: str, supervisor_effective: bool) -> str:
    if supervisor_effective:
        return "المشرف الأكاديمي"
    if role == "head_of_department" and active_mode in ("", "head", "hod", "department_head"):
        return "رئيس القسم (استبيانات الأستاذ)"
    if role == "head_of_department" and active_mode == "instructor":
        return "رئيس القسم — وضع الأستاذ"
    return RESPONDENT_ROLE_LABELS.get(
        survey_respondent_role(role, active_mode), role
    )


def _supervisor_report_status(conn, instructor_id, semester: str) -> dict:
    if not instructor_id:
        return {"submitted": False, "submitted_at": None}
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT submitted_at FROM supervisor_quality_reports
        WHERE supervisor_instructor_id = ? AND semester = ?
        LIMIT 1
        """,
        (int(instructor_id), semester),
    ).fetchone()
    if not row:
        return {"submitted": False, "submitted_at": None}
    return {"submitted": True, "submitted_at": row[0]}


def _count_supervisor_templates(conn) -> int:
    return sum(
        1
        for t in list_templates(conn)
        if (t.get("respondent_role") or "") == "supervisor"
        and not int(t.get("legacy_course_eval") or 0)
    )


def register_survey_platform_routes(bp) -> None:
    @bp.route("/surveys")
    @login_required
    def surveys_hub():
        role = _normalize_role((session.get("user_role") or "").strip())
        active_mode = _session_active_mode(role)
        is_supervisor_db = session.get("is_supervisor")
        supervisor_effective = is_supervisor_effective_session(role, is_supervisor_db, active_mode)
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            sess = _session_payload()
            pending = list_pending_for_user(
                conn,
                user_role=role,
                session_data=sess,
                semester=sem,
                department_id=dept_id,
                active_mode=active_mode,
            )
            course_eval_link = None
            if role == "student":
                course_eval_link = "/students/evaluations/"
            eff = survey_respondent_role(role, active_mode)
            fill_guide = ROLE_SURVEY_FILL_GUIDE.get(role) or ROLE_SURVEY_FILL_GUIDE.get(eff, "")
            respondent_label = _active_mode_label_ar(role, active_mode, supervisor_effective)

            instructor_pending: list = []
            show_instructor_cross = False
            instructor_all_done = False
            if supervisor_effective and session.get("instructor_id"):
                instructor_pending = list_pending_for_respondent_role(
                    conn,
                    respondent_role="instructor",
                    session_data=sess,
                    semester=sem,
                    department_id=dept_id,
                )
                show_instructor_cross = True
                instructor_all_done = len(instructor_pending) == 0

            supervisor_report = _supervisor_report_status(
                conn, session.get("instructor_id"), sem
            )
            supervisor_template_count = _count_supervisor_templates(conn) if supervisor_effective else 0
            dept_missing = supervisor_effective and dept_id is None and supervisor_template_count > 0

        return render_template(
            "survey_hub.html",
            pending=pending,
            semester=sem,
            user_role=role,
            respondent_role=eff,
            respondent_label=respondent_label,
            fill_guide=fill_guide,
            course_eval_link=course_eval_link,
            show_results_link=role in ("admin", "admin_main", "head_of_department"),
            supervisor_effective=supervisor_effective,
            active_mode=active_mode,
            show_instructor_cross=show_instructor_cross,
            instructor_pending=instructor_pending,
            instructor_all_done=instructor_all_done,
            supervisor_report=supervisor_report,
            supervisor_template_count=supervisor_template_count,
            dept_missing=dept_missing,
            department_id=dept_id,
        )

    @bp.route("/surveys/fill/<template_code>", methods=["GET"])
    @login_required
    def survey_fill_page(template_code: str):
        role = _normalize_role((session.get("user_role") or "").strip())
        active_mode = _session_active_mode(role)
        with get_connection() as conn:
            template = get_template_by_code(conn, template_code)
            if not template:
                return jsonify({"status": "error", "message": "الاستبيان غير موجود"}), 404
            allowed = (template.get("respondent_role") or "").strip()
            eff = survey_respondent_role(role, active_mode)
            if eff != allowed and not (role in ("admin", "admin_main") and request.args.get("preview")):
                return jsonify({"status": "error", "message": "غير مصرح بهذا الاستبيان"}), 403
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            subj_type, subj_id = _resolve_subject(
                conn, template, department_id=dept_id, subject_id_arg=dept_id
            )
            questions = list_template_questions(conn, int(template["id"]))
        return render_template(
            "survey_fill.html",
            template=template,
            questions=questions,
            semester=sem,
            subject_type=subj_type,
            subject_id=subj_id,
            likert_labels=likert_labels_ar(),
            department_id=dept_id,
        )

    @bp.route("/surveys/submit", methods=["POST"])
    @login_required
    def survey_submit():
        role = _normalize_role((session.get("user_role") or "").strip())
        active_mode = _session_active_mode(role)
        data = request.get_json(force=True) if request.is_json else request.form
        code = (data.get("template_code") or "").strip()
        sem = (data.get("semester") or "").strip()
        comments = (data.get("comments") or "").strip()
        try:
            subj_id = int(data.get("subject_id") or 0)
        except (TypeError, ValueError):
            subj_id = 0
        subj_type = (data.get("subject_type") or "").strip()
        with get_connection() as conn:
            if not sem:
                sem = term_label_from_conn(conn)
            template = get_template_by_code(conn, code)
            if not template:
                return jsonify({"status": "error", "message": "الاستبيان غير موجود"}), 404
            eff = survey_respondent_role(role, active_mode)
            if eff != (template.get("respondent_role") or "").strip():
                return jsonify({"status": "error", "message": "غير مصرح"}), 403
            dept_id = _user_department_id(conn)
            if not subj_type:
                subj_type, subj_id = _resolve_subject(
                    conn, template, department_id=dept_id, subject_id_arg=dept_id
                )
            questions = list_template_questions(conn, int(template["id"]))
            answers = parse_answers_payload(dict(data), questions)
            resp_role, resp_id = _respondent_key_from_session(eff)
            if not resp_id:
                return jsonify({"status": "error", "message": "تعذر تحديد هوية المُقيِّم"}), 400
            try:
                rid = submit_survey_response(
                    conn,
                    template_code=code,
                    semester=sem,
                    respondent_role=resp_role,
                    respondent_id=resp_id,
                    subject_type=subj_type,
                    subject_id=subj_id,
                    department_id=dept_id,
                    answers=answers,
                    comments=comments,
                    submitted_by=(session.get("user") or "").strip(),
                )
                conn.commit()
            except ValueError as e:
                return jsonify({"status": "error", "message": str(e)}), 400
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"status": "ok", "response_id": rid})
        return redirect(url_for("academic_quality.surveys_hub"))

    @bp.route("/surveys/results")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_results_page():
        code = (request.args.get("template") or "").strip()
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            templates = list_templates(conn)
            aggregates = []
            if code:
                aggregates = [aggregate_template(conn, code, semester=sem, department_id=dept_id)]
            else:
                for t in templates:
                    if int(t.get("legacy_course_eval") or 0):
                        continue
                    aggregates.append(
                        aggregate_template(conn, t["code"], semester=sem, department_id=dept_id)
                    )
            metrics = survey_metrics_for_quality(conn, sem, dept_id)
            tpl_by_code = {t["code"]: t for t in templates}
            from backend.core.survey_platform import RESPONDENT_ROLE_LABELS

            enriched = []
            for agg in aggregates:
                tc = agg.get("template_code") or ""
                tpl = tpl_by_code.get(tc, {})
                cnt = int(agg.get("response_count") or 0)
                mn = int(agg.get("min_aggregate") or 1)
                enriched.append(
                    {
                        **agg,
                        "respondent_role": tpl.get("respondent_role"),
                        "respondent_label": RESPONDENT_ROLE_LABELS.get(
                            (tpl.get("respondent_role") or "").strip(), "—"
                        ),
                        "fill_url": f"/academic_quality/surveys/fill/{tc}",
                        "progress_pct": min(100, int((cnt / mn) * 100)) if mn > 0 else 0,
                        "remaining": max(0, mn - cnt),
                    }
                )
            aggregates = enriched
            cur = conn.cursor()
            course_eval_row = cur.execute(
                "SELECT COUNT(*) FROM course_evaluations WHERE semester = ?",
                (sem,),
            ).fetchone()
            course_eval_count = int((course_eval_row[0] if course_eval_row else 0) or 0)
        return render_template(
            "survey_results.html",
            aggregates=aggregates,
            templates=templates,
            semester=sem,
            selected_template=code,
            survey_metrics=metrics,
            course_eval_count=course_eval_count,
        )

    @bp.route("/api/surveys/pending")
    @login_required
    def api_surveys_pending():
        role = _normalize_role((session.get("user_role") or "").strip())
        active_mode = _session_active_mode(role)
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            pending = list_pending_for_user(
                conn,
                user_role=role,
                session_data=_session_payload(),
                semester=sem,
                department_id=dept_id,
                active_mode=active_mode,
            )
        return jsonify({"status": "ok", "semester": sem, "pending": pending})

    @bp.route("/api/surveys/aggregate")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def api_surveys_aggregate():
        code = (request.args.get("template_code") or request.args.get("code") or "").strip()
        if not code:
            return jsonify({"status": "error", "message": "template_code مطلوب"}), 400
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            agg = aggregate_template(conn, code, semester=sem, department_id=dept_id)
        return jsonify({"status": "ok", "aggregate": agg})

    @bp.route("/api/surveys/metrics")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def api_surveys_metrics():
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            m = survey_metrics_for_quality(conn, sem, dept_id)
        return jsonify({"status": "ok", "semester": sem, "survey_metrics": m})

    @bp.route("/surveys/export.xlsx")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_xlsx():
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            rows = []
            for t in list_templates(conn):
                if int(t.get("legacy_course_eval") or 0):
                    continue
                agg = aggregate_template(conn, t["code"], semester=sem, department_id=dept_id)
                rows.append(
                    {
                        "الاستبيان": agg.get("title_ar"),
                        "الرمز": t["code"],
                        "الفصل": sem,
                        "عدد_الإجابات": agg.get("response_count"),
                        "الحد_الأدنى": agg.get("min_aggregate"),
                        "مجمّع": "نعم" if agg.get("aggregated") else "لا",
                        "النتيجة_%": agg.get("overall_score_percent"),
                    }
                )
            df = pd.DataFrame(rows)
        return excel_response_from_df(df, filename_prefix="survey_results")


def _respondent_key_from_session(respondent_role: str) -> tuple[str, str]:
    from backend.services.multi_surveys import _respondent_key

    return _respondent_key(respondent_role, _session_payload())
