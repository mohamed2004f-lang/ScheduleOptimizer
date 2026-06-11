"""مسارات منصة الاستبيانات (و-0 → و-5)."""

from __future__ import annotations

import os
from urllib.parse import quote

import io

from flask import jsonify, redirect, render_template, request, send_file, session, url_for

from backend.core.auth import (
    SESSION_ACTIVE_MODE,
    _normalize_role,
    get_admin_department_scope_id,
    is_supervisor_effective_session,
    login_required,
    role_required,
)
from backend.core.department_scope_policy import head_home_department_id, resolve_users_list_scope
from backend.core.survey_platform import (
    EMPLOYER_ORG_TYPES,
    EXTERNAL_SURVEY_CODES,
    RESPONDENT_ROLE_LABELS,
    ROLE_SURVEY_FILL_GUIDE,
)
from backend.services.survey_invites import (
    create_survey_invite,
    invite_fill_context,
    list_external_cycles,
    list_public_departments,
    list_public_tracks_for_department,
    list_survey_invites,
    submit_invite_survey,
    validate_invite,
)
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
from backend.services.survey_analytics import (
    build_course_eval_report,
    build_course_eval_sections_summary,
    export_course_eval_by_course_xlsx,
    export_course_eval_section_xlsx,
    export_course_eval_missing_sections_xlsx,
    export_course_eval_sections_xlsx,
    export_package_xlsx,
    export_single_survey_xlsx,
    is_exportable_template_code,
    list_course_eval_course_instructor_groups,
    prepare_combined_pdf_context,
    prepare_single_survey_pdf_context,
)
from backend.services.survey_accreditation import (
    accreditation_links_display,
    primary_evidence_indicator_code,
    register_survey_as_evidence,
)
from backend.services.survey_export_bundle import (
    build_external_survey_bundle_zip,
    build_survey_bundle_zip,
)
from backend.services.survey_external_analytics import (
    build_external_export_bytes,
    export_external_package_xlsx,
    prepare_external_combined_pdf_context,
    prepare_external_single_pdf_context,
)
from backend.services.survey_snapshots import (
    build_external_trends_chart_data,
    build_trends_chart_data,
    closure_reminder_status,
    close_cycle_and_snapshot,
    compare_cycle_snapshots,
    compare_semester_snapshots,
    get_cycle_closure,
    get_semester_closure,
    close_semester_and_snapshot,
    list_available_cycles_for_trends,
    list_available_semesters_for_trends,
    list_closed_cycles,
    list_closed_semesters,
    list_cycle_snapshots,
    list_semester_snapshots,
    survey_archive_dir,
)
from backend.services.utilities import get_connection, excel_response_from_df, pdf_response_from_html
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
            if role == "student":
                from backend.services.course_evaluations import list_pending_course_evaluations

                student_id = (sess.get("student_id") or sess.get("user") or "").strip()
                if student_id:
                    ce_pending = list_pending_course_evaluations(
                        conn, student_id, semester=sem
                    )
                    pending = ce_pending + pending
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

    @bp.route("/surveys/invite/<token>", methods=["GET"])
    def survey_invite_fill_page(token: str):
        try:
            with get_connection() as conn:
                ctx = invite_fill_context(conn, token)
        except ValueError as e:
            return render_template(
                "survey_invite_error.html",
                message=str(e),
            ), 400
        return render_template(
            "survey_invite_fill.html",
            **ctx,
            employer_org_types=EMPLOYER_ORG_TYPES,
        )

    @bp.route("/surveys/api/invite/<token>/submit", methods=["POST"])
    def survey_invite_submit_api(token: str):
        data = request.get_json(force=True) if request.is_json else request.form
        profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
        if not profile:
            profile = {
                k: data.get(k)
                for k in data.keys()
                if k not in ("answers", "comments", "template_code")
            }
        comments = (data.get("comments") or "").strip()
        try:
            with get_connection() as conn:
                invite = validate_invite(conn, token)
                ctx = invite_fill_context(conn, token)
                rid = submit_invite_survey(
                    conn,
                    token=token,
                    profile=profile,
                    answers_payload=dict(data),
                    comments=comments,
                )
                conn.commit()
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        return jsonify({
            "status": "ok",
            "response_id": rid,
            "template_code": invite.get("template_code"),
            "cycle_label": invite.get("cycle_label"),
            "open_comment_label": ctx.get("open_comment_label"),
        })

    @bp.route("/surveys/api/public/departments", methods=["GET"])
    def survey_public_departments_api():
        with get_connection() as conn:
            items = list_public_departments(conn)
        return jsonify({"status": "ok", "items": items})

    @bp.route("/surveys/api/public/tracks", methods=["GET"])
    def survey_public_tracks_api():
        try:
            dept_id = int(request.args.get("department_id") or 0)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "department_id مطلوب"}), 400
        if dept_id <= 0:
            return jsonify({"status": "error", "message": "department_id مطلوب"}), 400
        with get_connection() as conn:
            items = list_public_tracks_for_department(conn, dept_id)
        return jsonify({"status": "ok", "items": items})

    @bp.route("/surveys/invites")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def survey_invites_admin_page():
        template_code = (request.args.get("template") or "").strip()
        with get_connection() as conn:
            tpl_by_code = {t["code"]: t for t in list_templates(conn)}
            invites_raw = list_survey_invites(conn, template_code=template_code or None)
            invites = []
            for inv in invites_raw or []:
                tc = inv.get("template_code") or ""
                tpl = tpl_by_code.get(tc, {})
                invites.append({**inv, "title_ar": tpl.get("title_ar") or tc})
            templates = [
                t for t in tpl_by_code.values()
                if (t.get("code") or "") in EXTERNAL_SURVEY_CODES
            ]
        return render_template(
            "survey_invites_admin.html",
            invites=invites,
            templates=templates,
            selected_template=template_code,
            external_codes=sorted(EXTERNAL_SURVEY_CODES),
        )

    @bp.route("/surveys/api/invites", methods=["GET"])
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def survey_invites_list_api():
        template_code = (request.args.get("template") or "").strip() or None
        with get_connection() as conn:
            items = list_survey_invites(conn, template_code=template_code)
        return jsonify({"status": "ok", "items": items})

    @bp.route("/surveys/api/invites", methods=["POST"])
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def survey_invites_create_api():
        data = request.get_json(force=True) or {}
        try:
            with get_connection() as conn:
                invite = create_survey_invite(
                    conn,
                    template_code=(data.get("template_code") or "").strip(),
                    cycle_label=(data.get("cycle_label") or "").strip(),
                    invite_kind=(data.get("invite_kind") or "campaign").strip(),
                    label_ar=(data.get("label_ar") or "").strip(),
                    expires_days=int(data.get("expires_days") or 90),
                    max_uses=int(data.get("max_uses") or 0),
                    created_by=(session.get("user") or "").strip(),
                    notes=(data.get("notes") or "").strip(),
                )
                conn.commit()
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        base = request.url_root.rstrip("/")
        invite_url = f"{base}/academic_quality/surveys/invite/{invite['token']}"
        return jsonify({"status": "ok", "invite": invite, "invite_url": invite_url})

    @bp.route("/surveys/results")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_results_page():
        code = (request.args.get("template") or "").strip()
        results_view = (request.args.get("view") or "internal").strip().lower()
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            templates = list_templates(conn)
            external_cycles = list_external_cycles(conn)
            ext_cycle = (request.args.get("cycle") or "").strip()
            if not ext_cycle and external_cycles:
                ext_cycle = external_cycles[0]
            aggregates = []
            external_aggregates = []
            if results_view == "external":
                ext_codes = [code] if code and code in EXTERNAL_SURVEY_CODES else sorted(EXTERNAL_SURVEY_CODES)
                cycle_sem = ext_cycle or sem
                for ec in ext_codes:
                    external_aggregates.append(
                        aggregate_template(conn, ec, semester=cycle_sem, department_id=None)
                    )
            elif code:
                if code in EXTERNAL_SURVEY_CODES:
                    cycle_sem = ext_cycle or sem
                    aggregates = [aggregate_template(conn, code, semester=cycle_sem, department_id=None)]
                else:
                    aggregates = [aggregate_template(conn, code, semester=sem, department_id=dept_id)]
            else:
                for t in templates:
                    if int(t.get("legacy_course_eval") or 0):
                        continue
                    tc = t["code"]
                    if tc in EXTERNAL_SURVEY_CODES:
                        continue
                    aggregates.append(
                        aggregate_template(conn, tc, semester=sem, department_id=dept_id)
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
                        "accreditation_links": accreditation_links_display(
                            tc, conn, semester=sem, department_id=dept_id
                        ),
                        "evidence_indicator_code": primary_evidence_indicator_code(
                            tc, conn, semester=sem, department_id=dept_id
                        ),
                    }
                )
            aggregates = enriched
            ext_enriched = []
            for agg in external_aggregates:
                tc = agg.get("template_code") or ""
                tpl = tpl_by_code.get(tc, {})
                cnt = int(agg.get("response_count") or 0)
                mn = int(agg.get("min_aggregate") or 1)
                ext_enriched.append(
                    {
                        **agg,
                        "respondent_role": tpl.get("respondent_role"),
                        "respondent_label": RESPONDENT_ROLE_LABELS.get(
                            (tpl.get("respondent_role") or "").strip(), "—"
                        ),
                        "progress_pct": min(100, int((cnt / mn) * 100)) if mn > 0 else 0,
                        "remaining": max(0, mn - cnt),
                        "accreditation_links": accreditation_links_display(
                            tc, conn, semester=sem, department_id=dept_id
                        ),
                        "evidence_indicator_code": primary_evidence_indicator_code(
                            tc, conn, semester=sem, department_id=dept_id
                        ),
                    }
                )
            external_aggregates = ext_enriched
            cur = conn.cursor()
            course_eval_row = cur.execute(
                "SELECT COUNT(*) FROM course_evaluations WHERE semester = ?",
                (sem,),
            ).fetchone()
            course_eval_count = int((course_eval_row[0] if course_eval_row else 0) or 0)
            course_eval_sections = build_course_eval_sections_summary(
                conn, semester=sem, department_id=dept_id
            )
            course_eval_by_course = list_course_eval_course_instructor_groups(
                conn, semester=sem, department_id=dept_id
            )
            course_eval_summary = build_course_eval_report(
                conn, semester=sem, department_id=dept_id
            )
            semester_closure = get_semester_closure(conn, sem, dept_id)
            closure_reminder = closure_reminder_status(conn, sem, dept_id)
            cycle_closure = None
            if results_view == "external" and ext_cycle:
                cycle_closure = get_cycle_closure(conn, ext_cycle)
            from backend.services.survey_analytics import (
                build_course_eval_missing_sections_audit,
                get_course_eval_response_rate_percent,
            )

            course_eval_rate_percent = get_course_eval_response_rate_percent(conn)
            course_eval_missing_audit = build_course_eval_missing_sections_audit(
                conn, semester=sem, department_id=dept_id
            )
        return render_template(
            "survey_results.html",
            aggregates=aggregates,
            external_aggregates=external_aggregates,
            external_cycles=external_cycles,
            external_cycle=ext_cycle,
            cycle_closure=cycle_closure,
            results_view=results_view,
            templates=templates,
            semester=sem,
            selected_template=code,
            survey_metrics=metrics,
            course_eval_count=course_eval_count,
            course_eval_sections=course_eval_sections,
            course_eval_by_course=course_eval_by_course,
            course_eval_summary=course_eval_summary,
            semester_closure=semester_closure,
            closure_reminder=closure_reminder,
            compliance_map_url=(
                f"/academic_quality/accreditation/map?semester={quote(sem, safe='')}"
            ),
            course_eval_rate_percent=course_eval_rate_percent,
            course_eval_missing_audit=course_eval_missing_audit,
        )

    @bp.route("/surveys/trends")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_trends_page():
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            semesters = list_available_semesters_for_trends(conn, dept_id)
            closed = list_closed_semesters(conn, department_id=dept_id, limit=30)
            sem_a = (request.args.get("semester_a") or "").strip()
            sem_b = (request.args.get("semester_b") or "").strip()
            if not sem_a and len(semesters) > 1:
                sem_b = semesters[0]
                sem_a = semesters[1]
            elif not sem_b and semesters:
                sem_b = semesters[0]
            comparison = None
            if sem_a and sem_b:
                comparison = compare_semester_snapshots(
                    conn, sem_a, sem_b, department_id=dept_id
                )
            chart_data = build_trends_chart_data(conn, department_id=dept_id)
            external_cycles = list_available_cycles_for_trends(conn)
            closed_ext = list_closed_cycles(conn, limit=30)
            cycle_a = (request.args.get("cycle_a") or "").strip()
            cycle_b = (request.args.get("cycle_b") or "").strip()
            if not cycle_a and len(external_cycles) > 1:
                cycle_b = external_cycles[0]
                cycle_a = external_cycles[1]
            elif not cycle_b and external_cycles:
                cycle_b = external_cycles[0]
            external_comparison = None
            if cycle_a and cycle_b:
                external_comparison = compare_cycle_snapshots(conn, cycle_a, cycle_b)
            external_chart_data = build_external_trends_chart_data(conn)
            closure_reminder = closure_reminder_status(conn, sem, dept_id)
        return render_template(
            "survey_trends.html",
            semester=sem,
            semesters=semesters,
            closed_semesters=closed,
            semester_a=sem_a,
            semester_b=sem_b,
            comparison=comparison,
            chart_data=chart_data,
            external_cycles=external_cycles,
            closed_external_cycles=closed_ext,
            cycle_a=cycle_a,
            cycle_b=cycle_b,
            external_comparison=external_comparison,
            external_chart_data=external_chart_data,
            closure_reminder=closure_reminder,
        )

    @bp.route("/surveys/api/trends/chart", methods=["GET"])
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_trends_chart_api():
        with get_connection() as conn:
            dept_id = _user_department_id(conn)
            data = build_trends_chart_data(conn, department_id=dept_id)
        return jsonify({"status": "ok", **data})

    @bp.route("/surveys/api/closure_reminder", methods=["GET"])
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_closure_reminder_api():
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            reminder = closure_reminder_status(conn, sem, dept_id)
        return jsonify({"status": "ok", **reminder})

    @bp.route("/surveys/api/closure", methods=["GET"])
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_closure_status_api():
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            closure = get_semester_closure(conn, sem, dept_id)
            snapshots = list_semester_snapshots(conn, sem, dept_id) if closure else []
        return jsonify(
            {
                "status": "ok",
                "semester": sem,
                "is_closed": closure is not None,
                "closure": closure,
                "snapshots": snapshots,
            }
        )

    @bp.route("/surveys/api/close_semester", methods=["POST"])
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_close_semester_api():
        data = request.get_json(force=True) or {}
        with get_connection() as conn:
            sem = (data.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            force = str(data.get("force") or "").lower() in ("1", "true", "yes")
            register_ev = str(data.get("register_package_evidence") or "").lower() in (
                "1",
                "true",
                "yes",
            )
            try:
                result = close_semester_and_snapshot(
                    conn,
                    semester=sem,
                    department_id=dept_id,
                    actor=(session.get("user") or "").strip(),
                    force=force,
                    register_package_evidence=register_ev,
                )
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify(result), 200

    @bp.route("/surveys/api/cycle_closure", methods=["GET"])
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_cycle_closure_status_api():
        cycle = (request.args.get("cycle") or "").strip()
        if not cycle:
            return jsonify({"status": "error", "message": "cycle مطلوب"}), 400
        with get_connection() as conn:
            closure = get_cycle_closure(conn, cycle)
            snapshots = list_cycle_snapshots(conn, cycle) if closure else []
        return jsonify(
            {
                "status": "ok",
                "cycle_label": cycle,
                "is_closed": closure is not None,
                "closure": closure,
                "snapshots": snapshots,
            }
        )

    @bp.route("/surveys/api/close_cycle", methods=["POST"])
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_close_cycle_api():
        data = request.get_json(force=True) or {}
        cycle = (data.get("cycle_label") or data.get("cycle") or "").strip()
        if not cycle:
            return jsonify({"status": "error", "message": "cycle_label مطلوب"}), 400
        force = str(data.get("force") or "").lower() in ("1", "true", "yes")
        register_ev = str(data.get("register_package_evidence") or "").lower() in (
            "1",
            "true",
            "yes",
        )
        with get_connection() as conn:
            try:
                result = close_cycle_and_snapshot(
                    conn,
                    cycle_label=cycle,
                    actor=(session.get("user") or "").strip(),
                    force=force,
                    register_package_evidence=register_ev,
                )
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify(result), 200

    @bp.route("/surveys/api/snapshots/compare", methods=["GET"])
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_compare_snapshots_api():
        sem_a = (request.args.get("semester_a") or "").strip()
        sem_b = (request.args.get("semester_b") or "").strip()
        if not sem_a or not sem_b:
            return jsonify({"status": "error", "message": "semester_a و semester_b مطلوبان"}), 400
        with get_connection() as conn:
            dept_id = _user_department_id(conn)
            data = compare_semester_snapshots(
                conn, sem_a, sem_b, department_id=dept_id
            )
        return jsonify({"status": "ok", **data})

    @bp.route("/surveys/archives/<path:filename>")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_download_archive(filename: str):
        safe = os.path.basename((filename or "").strip())
        if not safe or safe != filename:
            return jsonify({"status": "error", "message": "اسم ملف غير صالح"}), 400
        path = os.path.join(survey_archive_dir(), safe)
        if not os.path.isfile(path):
            return jsonify({"status": "error", "message": "الملف غير موجود"}), 404
        return send_file(
            path,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=safe,
        )

    @bp.route("/surveys/api/register_evidence", methods=["POST"])
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_register_evidence_api():
        """رفع تقرير استبيان كشاهد في خريطة امتثال الاعتماد."""
        data = request.get_json(force=True) or {}
        template_code = (data.get("template_code") or "").strip()
        indicator_code = (data.get("indicator_code") or "").strip().upper()
        if not template_code:
            return jsonify({"status": "error", "message": "template_code مطلوب"}), 400
        with get_connection() as conn:
            if not is_exportable_template_code(conn, template_code):
                return jsonify({"status": "error", "message": "قالب الاستبيان غير موجود"}), 404
            if not indicator_code:
                indicator_code = primary_evidence_indicator_code(template_code, conn) or ""
            if not indicator_code:
                return jsonify({"status": "error", "message": "لا يوجد مؤشر اعتماد مرتبط بهذا الاستبيان"}), 400
            sem = (
                (data.get("cycle") or data.get("cycle_label") or data.get("semester") or "")
                .strip()
                or term_label_from_conn(conn)
            )
            dept_id = _user_department_id(conn)
            if template_code in EXTERNAL_SURVEY_CODES:
                dept_id = None
            try:
                result = register_survey_as_evidence(
                    conn,
                    template_code=template_code,
                    semester=sem,
                    department_id=dept_id,
                    indicator_code=indicator_code,
                    uploaded_by=(session.get("user") or "").strip(),
                )
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify({"status": "ok", **result}), 200

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
        """ملخص سريع (صف واحد لكل استبيان) — للتوافق مع الإصدارات السابقة."""
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

    @bp.route("/surveys/export/package")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_package_html():
        """معاينة HTML لتقرير الاستبيانات الموحّد."""
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            include_ce = (request.args.get("include_course_eval") or "1").strip().lower() not in (
                "0",
                "false",
                "no",
            )
            ctx = prepare_combined_pdf_context(
                conn,
                semester=sem,
                department_id=dept_id,
                include_course_eval=include_ce,
            )
        return render_template("survey_export_package.html", for_pdf=False, **ctx)

    @bp.route("/surveys/export/package.pdf")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_package_pdf():
        """تقرير PDF موحّد للاستبيانات."""
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            include_ce = (request.args.get("include_course_eval") or "1").strip().lower() not in (
                "0",
                "false",
                "no",
            )
            ctx = prepare_combined_pdf_context(
                conn,
                semester=sem,
                department_id=dept_id,
                include_course_eval=include_ce,
            )
        html = render_template("survey_export_package.html", for_pdf=True, **ctx)
        sem_slug = (ctx.get("semester") or "report").replace(" ", "_")[:40]
        return pdf_response_from_html(html, filename_prefix=f"survey_package_{sem_slug}")

    @bp.route("/surveys/export/external/package.xlsx")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_external_package_xlsx():
        cycle = (request.args.get("cycle") or "").strip()
        if not cycle:
            return jsonify({"status": "error", "message": "cycle مطلوب"}), 400
        with get_connection() as conn:
            return export_external_package_xlsx(conn, cycle_label=cycle)

    @bp.route("/surveys/export/external/package.pdf")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_external_package_pdf():
        cycle = (request.args.get("cycle") or "").strip()
        if not cycle:
            return jsonify({"status": "error", "message": "cycle مطلوب"}), 400
        with get_connection() as conn:
            ctx = prepare_external_combined_pdf_context(conn, cycle_label=cycle)
        html = render_template("survey_export_package.html", for_pdf=True, **ctx)
        cycle_slug = (cycle or "report").replace(" ", "_")[:40]
        return pdf_response_from_html(html, filename_prefix=f"survey_external_{cycle_slug}")

    @bp.route("/surveys/export/external/bundle.zip")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_external_bundle_zip():
        cycle = (request.args.get("cycle") or "").strip()
        if not cycle:
            return jsonify({"status": "error", "message": "cycle مطلوب"}), 400
        include_pdf = (request.args.get("include_pdf") or "1").strip().lower() not in (
            "0",
            "false",
            "no",
        )
        with get_connection() as conn:
            raw, filename, _meta = build_external_survey_bundle_zip(
                conn,
                cycle_label=cycle,
                include_pdf=include_pdf,
                render_template=render_template,
            )
        return send_file(
            io.BytesIO(raw),
            mimetype="application/zip",
            as_attachment=True,
            download_name=filename,
        )

    @bp.route("/surveys/export/external/<template_code>.xlsx")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_external_single_xlsx(template_code: str):
        code = (template_code or "").strip()
        if code not in EXTERNAL_SURVEY_CODES:
            return jsonify({"status": "error", "message": "قالب خارجي غير معروف"}), 404
        cycle = (request.args.get("cycle") or "").strip()
        if not cycle:
            return jsonify({"status": "error", "message": "cycle مطلوب"}), 400
        with get_connection() as conn:
            raw, filename, _report = build_external_export_bytes(
                conn, code, cycle_label=cycle
            )
        return send_file(
            io.BytesIO(raw),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename,
        )

    @bp.route("/surveys/export/external/<template_code>.pdf")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_external_single_pdf(template_code: str):
        code = (template_code or "").strip()
        if code not in EXTERNAL_SURVEY_CODES:
            return jsonify({"status": "error", "message": "قالب خارجي غير معروف"}), 404
        cycle = (request.args.get("cycle") or "").strip()
        if not cycle:
            return jsonify({"status": "error", "message": "cycle مطلوب"}), 400
        with get_connection() as conn:
            ctx = prepare_external_single_pdf_context(conn, code, cycle_label=cycle)
            if not ctx:
                return jsonify({"status": "error", "message": "قالب الاستبيان غير موجود"}), 404
        html = render_template("survey_export_single.html", for_pdf=True, **ctx)
        return pdf_response_from_html(html, filename_prefix=ctx.get("filename_prefix", f"survey_{code}"))

    @bp.route("/surveys/export/bundle.zip")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_bundle_zip():
        """حزمة ZIP: package + تقارير فردية (Excel وPDF إن توفر wkhtmltopdf)."""
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            include_ce = (request.args.get("include_course_eval") or "1").strip().lower() not in (
                "0",
                "false",
                "no",
            )
            include_pdf = (request.args.get("include_pdf") or "1").strip().lower() not in (
                "0",
                "false",
                "no",
            )
            raw, filename, _meta = build_survey_bundle_zip(
                conn,
                semester=sem,
                department_id=dept_id,
                include_course_eval=include_ce,
                include_pdf=include_pdf,
                render_template=render_template,
            )
        return send_file(
            io.BytesIO(raw),
            mimetype="application/zip",
            as_attachment=True,
            download_name=filename,
        )

    @bp.route("/surveys/export/package.xlsx")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_package_xlsx():
        """تقرير Excel موحّد متعدد الأوراق (ملخص + معايير + تحليل + بنود كل استبيان)."""
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            include_ce = (request.args.get("include_course_eval") or "1").strip().lower() not in (
                "0",
                "false",
                "no",
            )
            return export_package_xlsx(
                conn,
                semester=sem,
                department_id=dept_id,
                include_course_eval=include_ce,
            )

    @bp.route("/surveys/export/course_eval_sections.xlsx")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_course_eval_sections_xlsx():
        """تصدير تقييم المقررات — ملخص كل شعبة + تجميع مقرر/أستاذ."""
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            return export_course_eval_sections_xlsx(
                conn, semester=sem, department_id=dept_id
            )

    @bp.route("/surveys/export/course_eval_missing_sections.xlsx")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_course_eval_missing_sections_xlsx():
        """تصدير تدقيق شعب الجدول التي لم يُرسَل لها أي تقييم مقرر."""
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            return export_course_eval_missing_sections_xlsx(
                conn, semester=sem, department_id=dept_id
            )

    @bp.route("/surveys/export/course_eval/section/<int:section_id>.xlsx")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_course_eval_section_xlsx(section_id: int):
        """تصدير تقييم شعبة واحدة."""
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            resp = export_course_eval_section_xlsx(conn, section_id, semester=sem)
            if resp is None:
                return jsonify({"status": "error", "message": "الشعبة غير موجودة أو بلا تقييمات"}), 404
            return resp

    @bp.route("/surveys/export/course_eval/by-course.xlsx")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_course_eval_by_course_xlsx():
        """تجميع تقييمات المقرر لنفس الأستاذ عبر شعب متعددة."""
        course_name = (request.args.get("course_name") or "").strip()
        try:
            instructor_id = int(request.args.get("instructor_id") or 0)
        except (TypeError, ValueError):
            instructor_id = 0
        if not course_name or not instructor_id:
            return jsonify({"status": "error", "message": "course_name و instructor_id مطلوبان"}), 400
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            resp = export_course_eval_by_course_xlsx(
                conn,
                course_name,
                instructor_id,
                semester=sem,
                department_id=dept_id,
            )
            if resp is None:
                return jsonify({"status": "error", "message": "لا توجد تقييمات لهذا المقرر والأستاذ"}), 404
            return resp

    @bp.route("/surveys/export/<template_code>")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_single_html(template_code: str):
        """معاينة HTML لتقرير استبيان واحد."""
        code = (template_code or "").strip()
        with get_connection() as conn:
            if not is_exportable_template_code(conn, code):
                return jsonify({"status": "error", "message": "قالب الاستبيان غير موجود"}), 404
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            ctx = prepare_single_survey_pdf_context(
                conn, code, semester=sem, department_id=dept_id
            )
            if not ctx:
                return jsonify({"status": "error", "message": "قالب الاستبيان غير موجود"}), 404
        return render_template("survey_export_single.html", for_pdf=False, **ctx)

    @bp.route("/surveys/export/<template_code>.pdf")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_single_pdf(template_code: str):
        """تقرير PDF لاستبيان واحد."""
        code = (template_code or "").strip()
        with get_connection() as conn:
            if not is_exportable_template_code(conn, code):
                return jsonify({"status": "error", "message": "قالب الاستبيان غير موجود"}), 404
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            ctx = prepare_single_survey_pdf_context(
                conn, code, semester=sem, department_id=dept_id
            )
            if not ctx:
                return jsonify({"status": "error", "message": "قالب الاستبيان غير موجود"}), 404
        html = render_template("survey_export_single.html", for_pdf=True, **ctx)
        return pdf_response_from_html(html, filename_prefix=ctx.get("filename_prefix", f"survey_{code}"))

    @bp.route("/surveys/export/<template_code>.xlsx")
    @login_required
    @role_required("admin", "admin_main", "head_of_department")
    def surveys_export_single_xlsx(template_code: str):
        """تقرير Excel مفصّل لاستبيان واحد."""
        code = (template_code or "").strip()
        with get_connection() as conn:
            if not is_exportable_template_code(conn, code):
                return jsonify({"status": "error", "message": "قالب الاستبيان غير موجود"}), 404
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _user_department_id(conn)
            return export_single_survey_xlsx(
                conn,
                code,
                semester=sem,
                department_id=dept_id,
            )


def _respondent_key_from_session(respondent_role: str) -> tuple[str, str]:
    from backend.services.multi_surveys import _respondent_key

    return _respondent_key(respondent_role, _session_payload())
