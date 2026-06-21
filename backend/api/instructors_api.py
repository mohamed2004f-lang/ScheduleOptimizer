"""
Instructors API Endpoints — بوابة ضمان الجودة للأستاذ (v1)
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, jsonify, request, session

from backend.core.auth import login_required, _normalize_role
from backend.services.instructor_portal import (
    build_instructor_quality_context,
    instructor_portal_session_allowed,
)
from backend.services.survey_platform_routes import _session_active_mode, _session_payload
from backend.services import utilities as db_util

logger = logging.getLogger(__name__)

instructors_api_bp = Blueprint("instructors_api", __name__, url_prefix="/api/v1/instructors")


class APIError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def handle_errors(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except APIError as e:
            return jsonify({"success": False, "error": e.message}), e.status_code
        except Exception as e:
            logger.exception("Unexpected error in instructors API")
            return jsonify({"success": False, "error": "Internal server error", "details": str(e)}), 500

    return decorated


@instructors_api_bp.route("/me/quality_context", methods=["GET"])
@login_required
@handle_errors
def api_v1_instructor_quality_context():
    if not instructor_portal_session_allowed():
        raise APIError("غير مصرح — هذه الواجهة لعضو هيئة التدريس فقط", 403)
    role = _normalize_role((session.get("user_role") or "").strip())
    active_mode = _session_active_mode(role)
    sem = (request.args.get("semester") or "").strip() or None
    with db_util.get_connection() as conn:
        data = build_instructor_quality_context(
            conn,
            role=role,
            session_data=_session_payload(),
            active_mode=active_mode,
            semester=sem,
        )
    return jsonify({"success": True, "data": data}), 200
