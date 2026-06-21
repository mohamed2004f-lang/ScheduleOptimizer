"""API قوالب الأدوار والصلاحيات."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, session

from backend.core.auth import role_required
from backend.core.permissions import (
    catalog_grouped,
    get_profile_by_code,
    list_role_profiles_for_ui,
    load_profile_permission_keys,
    load_user_overrides,
)
from backend.core.user_admin_policy import (
    assert_actor_may_modify_user,
    assignable_roles_for_actor,
    is_system_admin_session,
    user_dict_is_protected,
)
from backend.repositories import users_repo
from .utilities import get_connection

role_profiles_bp = Blueprint("role_profiles", __name__)
logger = logging.getLogger(__name__)


@role_profiles_bp.route("/catalog", methods=["GET"])
@role_required("system_admin", "college_dean", "academic_vice_dean", "admin_main")
def permission_catalog():
    return jsonify({"groups": catalog_grouped()})


@role_profiles_bp.route("/list", methods=["GET"])
@role_required("system_admin", "college_dean", "academic_vice_dean", "admin_main", "head_of_department")
def list_profiles():
    include_sys = is_system_admin_session(session)
    profiles = list_role_profiles_for_ui(include_system_admin=include_sys)
    return jsonify({
        "profiles": profiles,
        "assignable": assignable_roles_for_actor(session),
    })


@role_profiles_bp.route("/detail/<code>", methods=["GET"])
@role_required("system_admin", "college_dean", "academic_vice_dean", "admin_main")
def profile_detail(code: str):
    prof = get_profile_by_code(code)
    if not prof:
        return jsonify({"status": "error", "message": "القالب غير موجود"}), 404
    if prof.get("code") == "system_admin" and not is_system_admin_session(session):
        return jsonify({"status": "error", "message": "القالب غير موجود"}), 404
    with get_connection() as conn:
        keys = load_profile_permission_keys(conn, None, code)
    return jsonify({"profile": prof, "permissions": sorted(keys)})


@role_profiles_bp.route("/handover", methods=["POST"])
@role_required("system_admin", "college_dean", "academic_vice_dean", "admin_main")
def handover_permissions():
    """نقل قالب الدور والاستثناءات من مستخدم إلى آخر."""
    data = request.get_json(force=True) or {}
    from_username = (data.get("from_username") or "").strip()
    to_username = (data.get("to_username") or "").strip()
    if not from_username or not to_username:
        return jsonify({"status": "error", "message": "from_username و to_username مطلوبان"}), 400
    if from_username.lower() == to_username.lower():
        return jsonify({"status": "error", "message": "لا يمكن النقل إلى نفس الحساب"}), 400

    actor = (session.get("user") or "").strip() or "system"
    with get_connection() as conn:
        src_row = users_repo.fetch_user_row_by_username_ci(conn, from_username)
        tgt_row = users_repo.fetch_user_row_by_username_ci(conn, to_username)
        if not src_row or not tgt_row:
            return jsonify({"status": "error", "message": "أحد الحسابين غير موجود"}), 404
        src = users_repo._user_row_to_dict(src_row)
        tgt = users_repo._user_row_to_dict(tgt_row)
        for u in (src, tgt):
            ok, err = assert_actor_may_modify_user(session, u)
            if not ok:
                return jsonify({"status": "error", "message": err or "غير مسموح"}), 403
        if user_dict_is_protected(src) or user_dict_is_protected(tgt):
            if not is_system_admin_session(session):
                return jsonify({"status": "error", "message": "لا يمكن نقل صلاحيات حسابات محمية"}), 403

        cur = conn.cursor()
        cur.execute(
            """
            UPDATE users
            SET role_profile_id = ?, display_title_ar = ?, role = ?
            WHERE lower(username) = lower(?)
            """,
            (
                src.get("role_profile_id"),
                src.get("display_title_ar"),
                src.get("role"),
                to_username,
            ),
        )
        grants, denies = load_user_overrides(conn, from_username)
        cur.execute(
            "DELETE FROM user_permission_overrides WHERE lower(username) = lower(?)",
            (to_username,),
        )
        for pk in grants:
            cur.execute(
                """
                INSERT INTO user_permission_overrides (username, permission_key, granted)
                VALUES (?, ?, 1)
                ON CONFLICT(username, permission_key) DO UPDATE SET granted = 1
                """,
                (to_username, pk),
            )
        for pk in denies:
            cur.execute(
                """
                INSERT INTO user_permission_overrides (username, permission_key, granted)
                VALUES (?, ?, 0)
                ON CONFLICT(username, permission_key) DO UPDATE SET granted = 0
                """,
                (to_username, pk),
            )
        conn.commit()
        logger.info("role handover from=%s to=%s actor=%s", from_username, to_username, actor)

    return jsonify({"status": "ok", "message": "تم نقل القالب والصلاحيات"})
