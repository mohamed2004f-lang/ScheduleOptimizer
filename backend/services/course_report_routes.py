"""مسارات معاينة وطباعة تقارير جودة المقررات."""

from __future__ import annotations

from flask import abort, redirect, render_template, request, session, url_for

from backend.core.auth import login_required, role_required
from backend.core.department_scope_policy import resolve_effective_department_scope_id
from backend.services import course_delivery as cd
from backend.services.utilities import get_connection, pdf_response_from_html

_INDEX_ROLES = (
    "head_of_department",
    "admin_main",
    "admin",
    "system_admin",
    "college_dean",
    "academic_vice_dean",
)
_VIEW_ROLES = _INDEX_ROLES + ("instructor",)


def _college_wide_role() -> bool:
    return (session.get("user_role") or "").strip() in (
        "admin_main",
        "admin",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
    )


def _dept_scope(conn) -> int | None:
    if _college_wide_role() and request.args.get("all_departments") in ("1", "true", "yes"):
        return None
    if _college_wide_role() and not request.args.get("department_id"):
        # الافتراضي للكلية: كل الأقسام
        return None
    uname = (session.get("user") or session.get("username") or "").strip()
    return resolve_effective_department_scope_id(conn, uname)


def register_course_report_routes(bp) -> None:
    @bp.route("/course_reports")
    @login_required
    @role_required(*_INDEX_ROLES)
    def course_reports_index():
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or cd._current_semester_label(conn)
            status_filter = (request.args.get("status") or "").strip()
            dept_arg = request.args.get("department_id", type=int)
            if _college_wide_role():
                dept_id = dept_arg
            else:
                dept_id = _dept_scope(conn)
            ctx = cd.build_course_reports_index(
                conn,
                semester=sem,
                department_id=dept_id,
                status_filter=status_filter or None,
            )
            ctx["college_wide"] = _college_wide_role()
            ctx["status_filter"] = status_filter
            ctx["can_warn"] = (session.get("user_role") or "").strip() in (
                "head_of_department",
                "admin_main",
                "admin",
                "system_admin",
            )
        return render_template("course_reports_index.html", **ctx)

    @bp.route("/course_reports/package")
    @login_required
    @role_required(*_INDEX_ROLES)
    def course_reports_package_preview():
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or cd._current_semester_label(conn)
            college_wide = _college_wide_role()
            dept_id = None if college_wide else _dept_scope(conn)
            ctx = cd.build_course_reports_package_context(
                conn,
                semester=sem,
                department_id=dept_id,
                college_wide=college_wide,
            )
        return render_template("course_reports_package.html", for_pdf=False, **ctx)

    @bp.route("/course_reports/package.pdf")
    @login_required
    @role_required(*_INDEX_ROLES)
    def course_reports_package_pdf():
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or cd._current_semester_label(conn)
            college_wide = _college_wide_role()
            dept_id = None if college_wide else _dept_scope(conn)
            ctx = cd.build_course_reports_package_context(
                conn,
                semester=sem,
                department_id=dept_id,
                college_wide=college_wide,
            )
        html = render_template("course_reports_package.html", for_pdf=True, **ctx)
        slug = (ctx.get("semester") or "report").replace(" ", "_")[:40]
        return pdf_response_from_html(html, filename_prefix=f"course_reports_package_{slug}")

    @bp.route("/course_reports/<int:tgid>")
    @login_required
    @role_required(*_VIEW_ROLES)
    def course_report_preview(tgid: int):
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or None
            phase = (request.args.get("phase") or "").strip() or None
            allowed = cd.user_may_view_course_report(
                conn,
                teaching_group_id=tgid,
                user_role=(session.get("user_role") or "").strip(),
                instructor_id=session.get("instructor_id"),
                username=(session.get("user") or session.get("username") or "").strip(),
            )
            if not allowed:
                abort(403)
            ctx = cd.build_course_report_view(
                conn,
                teaching_group_id=tgid,
                semester=sem,
                phase=phase,
            )
            if not ctx:
                abort(404)
        return render_template("course_report_single.html", for_pdf=False, **ctx)

    @bp.route("/course_reports/<int:tgid>.pdf")
    @login_required
    @role_required(*_VIEW_ROLES)
    def course_report_pdf(tgid: int):
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or None
            phase = (request.args.get("phase") or "").strip() or None
            allowed = cd.user_may_view_course_report(
                conn,
                teaching_group_id=tgid,
                user_role=(session.get("user_role") or "").strip(),
                instructor_id=session.get("instructor_id"),
                username=(session.get("user") or session.get("username") or "").strip(),
            )
            if not allowed:
                abort(403)
            ctx = cd.build_course_report_view(
                conn,
                teaching_group_id=tgid,
                semester=sem,
                phase=phase,
            )
            if not ctx:
                abort(404)
        html = render_template("course_report_single.html", for_pdf=True, **ctx)
        cn = (ctx.get("course_name") or "course").replace(" ", "_")[:30]
        return pdf_response_from_html(html, filename_prefix=f"course_report_{tgid}_{cn}")
