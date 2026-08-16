"""حراسة مسارات بوابة الطالب والأستاذ (before_request)."""
from __future__ import annotations

from backend.core.auth_constants import SESSION_ACTIVE_MODE, SESSION_KEY
from backend.core.auth_roles import _normalize_role

_STUDENT_SURVEY_BLOCKED = (
    "/academic_quality/surveys/results",
    "/academic_quality/surveys/completion",
    "/academic_quality/surveys/trends",
    "/academic_quality/surveys/invites",
    "/academic_quality/survey_admin",
)

_STUDENT_ALLOWED_PREFIXES = (
    "/my_portal",
    "/my_registrations",
    "/my_schedule",
    "/my_exams",
    "/my_transcript",
    "/my_announcements",
    "/my_requests",
    "/my_course_page",
    "/my_course_pages",
    "/course_pages/",
    "/academic_quality/student/",
    "/students/evaluations",
    "/students/me",
    "/students/portal_summary",
    "/students/academic_progress",
    "/students/identity_context",
    "/students/get_registrations",
    "/students/eligible_courses",
    "/academic_quality/ilo/student/",
    "/academic_quality/ilo/api/student/",
    "/academic_quality/glossary",
    "/auth/",
    "/change_password",
    "/mfa",
    "/notifications",
    "/schedule/student_",
    "/schedule/meta",
    "/grades/transcript/",
    "/grades/export/",
    "/performance/status/",
    "/admin/settings/current_term",
    "/list_courses",
    "/enrollment/plans",
    "/registration_requests/",
    "/api/v1/students/me",
    "/transcript_page",
    "/static/",
    "/health",
    "/favicon",
)

_INSTRUCTOR_STUDENT_PORTAL_PREFIXES = (
    "/my_portal",
    "/my_registrations",
    "/my_transcript",
    "/my_announcements",
    "/my_requests",
    "/academic_quality/student/",
)


def student_portal_path_allowed(path: str) -> bool:
    """مسارات مسموحة للطالب (صفحات + APIs). الباقي يُحجب."""
    p = (path or "/").split("?")[0].rstrip("/") or "/"
    if p in ("/", "/login", "/logout"):
        return True
    if any(p.startswith(b) for b in _STUDENT_SURVEY_BLOCKED):
        return False
    if p.startswith("/academic_quality/surveys"):
        return True
    for prefix in _STUDENT_ALLOWED_PREFIXES:
        if p.startswith(prefix):
            return True
    return False


def register_student_route_guard(app) -> None:
    """يمنع الطالب من فتح صفحات الإدارة حتى لو ظهرت في الشريط لحظياً."""

    @app.before_request
    def _block_student_staff_routes():
        from flask import jsonify, redirect, request, session, url_for

        if request.method == "OPTIONS":
            return None
        if not session.get(SESSION_KEY):
            return None
        role = _normalize_role((session.get("user_role") or "").strip())
        if role != "student":
            return None
        path = request.path or "/"
        if student_portal_path_allowed(path):
            return None
        accept = (request.headers.get("Accept") or "").lower()
        is_api = (
            request.is_json
            or "application/json" in accept
            or path.startswith("/api/")
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        )
        if is_api:
            return jsonify({
                "status": "error",
                "message": "غير مصرح — هذه الصفحة للموظفين فقط",
                "code": "FORBIDDEN",
            }), 403
        return redirect(url_for("my_portal_page"))


def instructor_blocked_student_portal_path(path: str) -> bool:
    p = (path or "/").split("?")[0].rstrip("/") or "/"
    return any(p.startswith(prefix) for prefix in _INSTRUCTOR_STUDENT_PORTAL_PREFIXES)


def register_instructor_route_guard(app) -> None:
    """يمنع الأستاذ من صفحات بوابة الطالب (my_portal، كشف الطالب…)."""

    @app.before_request
    def _block_instructor_student_portal_routes():
        from flask import jsonify, redirect, request, session, url_for

        if request.method == "OPTIONS":
            return None
        if not session.get(SESSION_KEY):
            return None
        role = _normalize_role((session.get("user_role") or "").strip())
        if role not in ("instructor", "head_of_department"):
            return None
        if role == "head_of_department":
            active = (session.get(SESSION_ACTIVE_MODE) or "head").strip().lower()
            if active in ("", "head", "hod", "department_head"):
                return None
        path = request.path or "/"
        if not instructor_blocked_student_portal_path(path):
            return None
        accept = (request.headers.get("Accept") or "").lower()
        is_api = (
            request.is_json
            or "application/json" in accept
            or path.startswith("/api/")
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        )
        if is_api:
            return jsonify({
                "status": "error",
                "message": "هذه الصفحة للطلاب فقط",
                "code": "FORBIDDEN",
            }), 403
        return redirect(url_for("my_courses_page"))
