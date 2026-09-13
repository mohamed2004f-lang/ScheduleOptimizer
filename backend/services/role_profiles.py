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
    ADMIN_ONLY_HANDOVER_OFFICES,
    HANDOVER_EXCLUDED_ROLES,
    HANDOVER_OFFICE_ROLES,
    assert_actor_may_modify_user,
    assignable_roles_for_actor,
    is_principal_admin_session,
    is_system_admin_session,
    user_dict_is_protected,
)
from backend.repositories import users_repo
from .utilities import get_connection

role_profiles_bp = Blueprint("role_profiles", __name__)
logger = logging.getLogger(__name__)

_OFFICE_ROLE_LABELS_AR = {
    "college_dean": "عميد الكلية",
    "academic_vice_dean": "وكيل الشؤون العلمية",
    "head_of_department": "رئيس قسم",
    "staff": "موظف إداري / منصب إداري",
    "admin_main": "المسؤول الرئيسي",
    "system_admin": "مسؤول النظام",
    "instructor": "عضو هيئة تدريس",
}


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if value in (True, 1, "1", "true", "True", "yes", "on"):
        return True
    if value in (False, 0, "0", "false", "False", "no", "off"):
        return False
    return default


def _role_of(user: dict | None) -> str:
    from backend.core.auth_roles import _normalize_role

    return _normalize_role((user or {}).get("role") or "")


def _profile_id_by_code(conn, code: str) -> int | None:
    cur = conn.cursor()
    try:
        row = cur.execute(
            "SELECT id FROM role_profiles WHERE code = ? LIMIT 1",
            (code,),
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        return int(row[0] if not hasattr(row, "keys") else row["id"])
    except (TypeError, ValueError, KeyError):
        return None


def _office_label(conn, user: dict) -> str:
    title = (user.get("display_title_ar") or "").strip()
    if title:
        return title
    from backend.core.permissions import get_profile_by_id

    prof = get_profile_by_id(conn, user.get("role_profile_id"))
    if prof and (prof.get("name_ar") or "").strip():
        return str(prof.get("name_ar")).strip()
    role = _role_of(user)
    return _OFFICE_ROLE_LABELS_AR.get(role, role or "منصب")


def _fallback_after_office(conn, user: dict) -> tuple[str, int | None, str | None]:
    if user.get("instructor_id") is not None:
        return "instructor", _profile_id_by_code(conn, "instructor"), None
    return "staff", None, None


def _handover_items(conn, src: dict, *, actor_session) -> tuple[list[dict], str | None]:
    role = _role_of(src)
    if role in HANDOVER_EXCLUDED_ROLES:
        return [], "لا يمكن نقل صلاحيات حساب طالب — ليست لديه مناصب إدارية."

    grants, denies = load_user_overrides(conn, src.get("username") or "")
    override_count = len(grants) + len(denies)
    has_office = role in HANDOVER_OFFICE_ROLES
    office_restricted = has_office and role in ADMIN_ONLY_HANDOVER_OFFICES and not is_principal_admin_session(
        actor_session
    )
    blocked = None
    if role == "system_admin" and has_office:
        blocked = "لا يمكن نقل منصب مسؤول النظام."
        office_restricted = True

    items = []
    if has_office:
        label = f"المنصب الإداري: {_office_label(conn, src)}"
        items.append(
            {
                "key": "office",
                "label_ar": label,
                "enabled": not office_restricted and blocked is None,
                "default": not office_restricted and blocked is None,
                "restricted": bool(office_restricted or blocked),
                "note_ar": (
                    blocked
                    or (
                        "نقل منصب عميد الكلية أو المسؤول الرئيسي مقصور على الأدمن الرئيسي."
                        if office_restricted
                        else ""
                    )
                ),
            }
        )
    if override_count:
        items.append(
            {
                "key": "overrides",
                "label_ar": f"صلاحيات إضافية ممنوحة لهذا الحساب ({override_count})",
                "enabled": True,
                "default": True,
                "restricted": False,
                "count": override_count,
                "note_ar": "",
            }
        )
    if has_office and src.get("department_id") is not None and role in (
        "head_of_department",
        "staff",
    ):
        items.append(
            {
                "key": "department",
                "label_ar": "ارتباط القسم (رئاسة/نطاق القسم)",
                "enabled": not office_restricted,
                "default": not office_restricted,
                "restricted": bool(office_restricted),
                "note_ar": "",
            }
        )
    if has_office:
        fallback_role, _, _ = _fallback_after_office(conn, src)
        fallback_label = _OFFICE_ROLE_LABELS_AR.get(fallback_role, fallback_role)
        items.append(
            {
                "key": "revert_source",
                "label_ar": f"إعادة المصدر إلى «{fallback_label}» بعد النقل",
                "enabled": not office_restricted and blocked is None,
                "default": not office_restricted and blocked is None,
                "restricted": bool(office_restricted or blocked),
                "note_ar": "",
            }
        )
    if not items:
        blocked = blocked or "لا يوجد منصب إداري أو صلاحيات إضافية للنقل من هذا الحساب."
    return items, blocked


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


@role_profiles_bp.route("/handover_options", methods=["GET"])
@role_required("system_admin", "college_dean", "admin_main")
def handover_options():
    """عناصر النقل المتاحة لحساب مصدر (بدون طلبة)."""
    from_username = (request.args.get("from_username") or "").strip()
    if not from_username:
        return jsonify({"status": "error", "message": "from_username مطلوب"}), 400
    with get_connection() as conn:
        from backend.boot.role_profiles_seed import ensure_role_profile_tables, _is_pg

        ensure_role_profile_tables(conn, pg=_is_pg(conn))
        src_row = users_repo.fetch_user_row_by_username_ci(conn, from_username)
        if not src_row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404
        src = users_repo._user_row_to_dict(src_row)
        ok, err = assert_actor_may_modify_user(session, src)
        if not ok:
            return jsonify({"status": "error", "message": err or "غير مسموح"}), 403
        items, blocked = _handover_items(conn, src, actor_session=session)
    return jsonify(
        {
            "status": "ok",
            "from_username": src.get("username"),
            "role": src.get("role"),
            "display_title_ar": src.get("display_title_ar"),
            "items": items,
            "blocked_reason": blocked,
        }
    )


@role_profiles_bp.route("/handover", methods=["POST"])
@role_required("system_admin", "college_dean", "admin_main")
def handover_permissions():
    """تسليم منصب إداري وصلاحيات إضافية من حساب إلى آخر."""
    data = request.get_json(force=True) or {}
    from_username = (data.get("from_username") or "").strip()
    to_username = (data.get("to_username") or "").strip()
    if not from_username or not to_username:
        return jsonify({"status": "error", "message": "from_username و to_username مطلوبان"}), 400
    if from_username.lower() == to_username.lower():
        return jsonify({"status": "error", "message": "لا يمكن النقل إلى نفس الحساب"}), 400

    transfer_office = _as_bool(data.get("transfer_office"), True)
    transfer_overrides = _as_bool(data.get("transfer_overrides"), True)
    transfer_department = _as_bool(data.get("transfer_department"), True)
    revert_source = _as_bool(data.get("revert_source"), True)

    actor = (session.get("user") or "").strip() or "system"
    with get_connection() as conn:
        from backend.boot.role_profiles_seed import ensure_role_profile_tables, _is_pg

        ensure_role_profile_tables(conn, pg=_is_pg(conn))
        src_row = users_repo.fetch_user_row_by_username_ci(conn, from_username)
        tgt_row = users_repo.fetch_user_row_by_username_ci(conn, to_username)
        if not src_row or not tgt_row:
            return jsonify({"status": "error", "message": "أحد الحسابين غير موجود"}), 404
        src = users_repo._user_row_to_dict(src_row)
        tgt = users_repo._user_row_to_dict(tgt_row)
        src_role = _role_of(src)
        tgt_role = _role_of(tgt)
        if src_role in HANDOVER_EXCLUDED_ROLES or tgt_role in HANDOVER_EXCLUDED_ROLES:
            return jsonify({
                "status": "error",
                "message": "حسابات الطلبة مستثناة من نقل المناصب الإدارية",
            }), 400

        items, blocked = _handover_items(conn, src, actor_session=session)
        enabled_keys = {it["key"] for it in items if it.get("enabled")}
        if transfer_office and "office" not in enabled_keys:
            return jsonify({
                "status": "error",
                "message": blocked or "غير مسموح بنقل هذا المنصب",
            }), 403
        if transfer_overrides and "overrides" not in enabled_keys:
            transfer_overrides = False
        if transfer_department and "department" not in enabled_keys:
            transfer_department = False
        if revert_source and "revert_source" not in enabled_keys:
            revert_source = False

        if not (transfer_office or transfer_overrides or transfer_department):
            return jsonify({"status": "error", "message": "حدّد ما الذي تريد نقله"}), 400

        new_tgt_role = src.get("role") if transfer_office else None
        for u, new_role in ((src, None), (tgt, new_tgt_role)):
            ok, err = assert_actor_may_modify_user(session, u, new_role=new_role)
            if not ok:
                return jsonify({"status": "error", "message": err or "غير مسموح"}), 403
        if user_dict_is_protected(src) or user_dict_is_protected(tgt):
            if not is_system_admin_session(session):
                return jsonify({"status": "error", "message": "لا يمكن نقل صلاحيات حسابات محمية"}), 403
        if transfer_office and src_role in ADMIN_ONLY_HANDOVER_OFFICES and not is_principal_admin_session(session):
            return jsonify({
                "status": "error",
                "message": "نقل منصب عميد الكلية مقصور على الأدمن الرئيسي",
            }), 403
        if transfer_office and src_role == "system_admin":
            return jsonify({"status": "error", "message": "لا يمكن نقل منصب مسؤول النظام"}), 403
        if transfer_office and src_role == "head_of_department" and tgt.get("instructor_id") is None:
            return jsonify({
                "status": "error",
                "message": "الهدف يجب أن يكون مربوطاً بعضو هيئة تدريس لاستلام رئاسة القسم",
            }), 400

        src_name = src.get("username") or from_username
        tgt_name = tgt.get("username") or to_username
        cur = conn.cursor()
        if transfer_office:
            cur.execute(
                """
                UPDATE users
                SET role_profile_id = ?, display_title_ar = ?, role = ?,
                    is_dept_quality_coordinator = ?
                WHERE lower(username) = lower(?)
                """,
                (
                    src.get("role_profile_id"),
                    src.get("display_title_ar"),
                    src.get("role"),
                    int(src.get("is_dept_quality_coordinator") or 0),
                    tgt_name,
                ),
            )
        if transfer_department and src.get("department_id") is not None:
            cur.execute(
                """
                UPDATE users SET department_id = ?
                WHERE lower(username) = lower(?)
                """,
                (src.get("department_id"), tgt_name),
            )
        if transfer_overrides:
            grants, denies = load_user_overrides(conn, src_name)
            cur.execute(
                "DELETE FROM user_permission_overrides WHERE lower(username) = lower(?)",
                (tgt_name,),
            )
            for pk in grants:
                cur.execute(
                    """
                    INSERT INTO user_permission_overrides (username, permission_key, granted)
                    VALUES (?, ?, 1)
                    ON CONFLICT(username, permission_key) DO UPDATE SET granted = 1
                    """,
                    (tgt_name, pk),
                )
            for pk in denies:
                cur.execute(
                    """
                    INSERT INTO user_permission_overrides (username, permission_key, granted)
                    VALUES (?, ?, 0)
                    ON CONFLICT(username, permission_key) DO UPDATE SET granted = 0
                    """,
                    (tgt_name, pk),
                )
            cur.execute(
                "DELETE FROM user_permission_overrides WHERE lower(username) = lower(?)",
                (src_name,),
            )
        if transfer_office and revert_source:
            fb_role, fb_profile, fb_title = _fallback_after_office(conn, src)
            ok, err = assert_actor_may_modify_user(session, src, new_role=fb_role)
            if not ok:
                conn.rollback()
                return jsonify({"status": "error", "message": err or "غير مسموح"}), 403
            cur.execute(
                """
                UPDATE users
                SET role = ?, role_profile_id = ?, display_title_ar = ?,
                    is_dept_quality_coordinator = 0
                WHERE lower(username) = lower(?)
                """,
                (fb_role, fb_profile, fb_title, src_name),
            )
        conn.commit()
        logger.info(
            "role handover from=%s to=%s office=%s overrides=%s dept=%s revert=%s actor=%s",
            from_username, to_username, transfer_office, transfer_overrides,
            transfer_department, revert_source, actor,
        )

    return jsonify({"status": "ok", "message": "تم نقل الصلاحيات المحددة"})


def _ensure_permission_definition(conn, permission_key: str) -> None:
    from backend.core.permissions import PERMISSION_CATALOG

    item = next((p for p in PERMISSION_CATALOG if p["key"] == permission_key), None)
    if not item:
        return
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO permission_definitions (key, group_key, group_label_ar, label_ar, sort_order)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(key) DO NOTHING
        """,
        (item["key"], item["group_key"], item["group_label_ar"], item["label_ar"], 0),
    )


@role_profiles_bp.route("/user_overrides", methods=["GET"])
@role_required("system_admin", "college_dean", "admin_main")
def get_user_overrides():
    username = (request.args.get("username") or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "username مطلوب"}), 400
    with get_connection() as conn:
        row = users_repo.fetch_user_row_by_username_ci(conn, username)
        if not row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404
        tgt = users_repo._user_row_to_dict(row)
        ok, err = assert_actor_may_modify_user(session, tgt)
        if not ok:
            return jsonify({"status": "error", "message": err or "غير مسموح"}), 403
        grants, denies = load_user_overrides(conn, username)
    from backend.core.permissions import CAN_ADD_DEPARTMENT_USERS

    return jsonify({
        "status": "ok",
        "username": username,
        "role": tgt.get("role"),
        "grants": sorted(grants),
        "denies": sorted(denies),
        "can_add_department_users": CAN_ADD_DEPARTMENT_USERS in grants
        and CAN_ADD_DEPARTMENT_USERS not in denies,
    })


@role_profiles_bp.route("/user_overrides", methods=["POST"])
@role_required("system_admin", "college_dean", "admin_main")
def set_user_override():
    """منح أو إلغاء صلاحية إضافية لحساب معيّن (مثل إضافة مستخدمي القسم لرئيس القسم)."""
    from backend.core.permissions import (
        CAN_ADD_DEPARTMENT_USERS,
        GRANTABLE_USER_OVERRIDE_KEYS,
    )
    from backend.core.user_admin_policy import can_grant_hod_department_users_session
    from backend.core.auth_roles import _normalize_role

    if not can_grant_hod_department_users_session(session):
        return jsonify({"status": "error", "message": "غير مسموح"}), 403

    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    permission_key = (data.get("permission_key") or CAN_ADD_DEPARTMENT_USERS).strip()
    granted_raw = data.get("granted")
    if granted_raw in (True, 1, "1", "true", "True", "yes"):
        granted = True
    elif granted_raw in (False, 0, "0", "false", "False", "no"):
        granted = False
    else:
        return jsonify({"status": "error", "message": "granted مطلوب (true/false)"}), 400
    if not username:
        return jsonify({"status": "error", "message": "username مطلوب"}), 400
    if permission_key not in GRANTABLE_USER_OVERRIDE_KEYS:
        return jsonify({"status": "error", "message": "صلاحية غير مسموح منحها من هنا"}), 400

    actor = (session.get("user") or "").strip() or "system"
    with get_connection() as conn:
        from backend.boot.role_profiles_seed import ensure_role_profile_tables, _is_pg

        ensure_role_profile_tables(conn, pg=_is_pg(conn))
        tgt_row = users_repo.fetch_user_row_by_username_ci(conn, username)
        if not tgt_row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404
        tgt = users_repo._user_row_to_dict(tgt_row)
        ok, err = assert_actor_may_modify_user(session, tgt)
        if not ok:
            return jsonify({"status": "error", "message": err or "غير مسموح"}), 403
        if user_dict_is_protected(tgt) and not is_system_admin_session(session):
            return jsonify({"status": "error", "message": "لا يمكن تعديل صلاحيات حساب محمي"}), 403
        target_role = _normalize_role(tgt.get("role") or "")
        if permission_key == CAN_ADD_DEPARTMENT_USERS and target_role != "head_of_department":
            return jsonify({
                "status": "error",
                "message": "هذه الصلاحية تُمنح لرئيس القسم فقط",
            }), 400

        _ensure_permission_definition(conn, permission_key)
        cur = conn.cursor()
        if granted:
            cur.execute(
                """
                INSERT INTO user_permission_overrides (username, permission_key, granted)
                VALUES (?, ?, 1)
                ON CONFLICT(username, permission_key) DO UPDATE SET granted = 1
                """,
                (tgt.get("username") or username, permission_key),
            )
        else:
            cur.execute(
                """
                DELETE FROM user_permission_overrides
                WHERE lower(username) = lower(?) AND permission_key = ?
                """,
                (username, permission_key),
            )
        conn.commit()
        logger.info(
            "user override username=%s key=%s granted=%s actor=%s",
            username, permission_key, granted, actor,
        )

    return jsonify({
        "status": "ok",
        "username": username,
        "permission_key": permission_key,
        "granted": granted,
        "message": "تم منح الصلاحية" if granted else "تم إلغاء الصلاحية",
    })
