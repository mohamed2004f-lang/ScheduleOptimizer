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
from backend.core.role_profile_policy import (
    CREATABLE_BASE_ROLES,
    assert_profile_creatable,
    assert_profile_editable,
    can_manage_role_profiles,
    normalize_scope_mode,
    profile_flags,
    role_profile_admin_enabled,
    sanitize_permission_keys,
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
from .utilities import get_connection, log_activity

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


def _active_profile_id_by_code(conn, code: str) -> int | None:
    cur = conn.cursor()
    try:
        row = cur.execute(
            """
            SELECT id FROM role_profiles
            WHERE code = ? AND COALESCE(is_active, 1) = 1
            LIMIT 1
            """,
            (code,),
        ).fetchone()
    except Exception:
        return _profile_id_by_code(conn, code)
    if not row:
        return None
    try:
        return int(row[0] if not hasattr(row, "keys") else row["id"])
    except (TypeError, ValueError, KeyError):
        return None


def _fallback_after_office(conn, user: dict) -> tuple[str, int | None, str | None]:
    if user.get("instructor_id") is not None:
        return "instructor", _active_profile_id_by_code(conn, "instructor"), None
    staff_pid = _active_profile_id_by_code(conn, "college_registrar") or _active_profile_id_by_code(
        conn, "staff"
    )
    return "staff", staff_pid, None


def _source_office_profile_inactive(conn, src: dict) -> bool:
    from backend.core.permissions import get_profile_by_id

    pid = src.get("role_profile_id")
    if pid is None:
        return False
    prof = get_profile_by_id(conn, pid)
    if not prof:
        return False
    return int(prof.get("is_active") if prof.get("is_active") is not None else 1) == 0


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
    archived_office = False
    if role == "system_admin" and has_office:
        blocked = "لا يمكن نقل منصب مسؤول النظام."
        office_restricted = True
    if has_office and _source_office_profile_inactive(conn, src):
        archived_office = True
        office_restricted = True
        blocked = blocked or "قالب المنصب مؤرشف — انقل الصلاحيات الإضافية فقط أو أعد تفعيل القالب."

    items = []
    if has_office:
        label = f"المنصب الإداري: {_office_label(conn, src)}"
        items.append(
            {
                "key": "office",
                "label_ar": label,
                "enabled": not office_restricted and blocked is None,
                "default": not office_restricted and blocked is None and not archived_office,
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
    from backend.core.permissions import GRANTABLE_USER_OVERRIDE_KEYS, PERMISSION_CATALOG

    label_by_key = {p["key"]: p.get("label_ar") or p["key"] for p in PERMISSION_CATALOG}
    grantable = [
        {"key": k, "label_ar": label_by_key.get(k, k)}
        for k in sorted(GRANTABLE_USER_OVERRIDE_KEYS)
    ]
    return jsonify({
        "groups": catalog_grouped(),
        "grantable_override_keys": grantable,
        "admin_enabled": role_profile_admin_enabled(),
        "can_manage": can_manage_role_profiles(session),
    })


@role_profiles_bp.route("/list", methods=["GET"])
@role_required("system_admin", "college_dean", "academic_vice_dean", "admin_main", "head_of_department")
def list_profiles():
    include_sys = is_system_admin_session(session)
    include_inactive = can_manage_role_profiles(session)
    with get_connection() as conn:
        profiles = list_role_profiles_for_ui(
            include_system_admin=include_sys,
            conn=conn,
            include_inactive=include_inactive,
        )
        assignable = assignable_roles_for_actor(session, conn=conn)
    for p in profiles:
        flags = profile_flags(p)
        p["locked"] = flags["locked"]
        p["editable"] = flags["editable"] and can_manage_role_profiles(session) and role_profile_admin_enabled()
    return jsonify({
        "profiles": profiles,
        "assignable": assignable,
        "admin_enabled": role_profile_admin_enabled(),
        "can_manage": can_manage_role_profiles(session),
        "creatable_base_roles": sorted(CREATABLE_BASE_ROLES),
    })


@role_profiles_bp.route("/detail/<code>", methods=["GET"])
@role_required("system_admin", "college_dean", "academic_vice_dean", "admin_main")
def profile_detail(code: str):
    from backend.core.capability_gates import panel_effective_keys_for_profile
    from backend.core.permissions import GRANTABLE_USER_OVERRIDE_KEYS

    with get_connection() as conn:
        prof = get_profile_by_code(code, conn=conn)
        if not prof:
            return jsonify({"status": "error", "message": "القالب غير موجود"}), 404
        if prof.get("code") == "system_admin" and not is_system_admin_session(session):
            return jsonify({"status": "error", "message": "القالب غير موجود"}), 404
        pid = prof.get("id")
        keys = load_profile_permission_keys(conn, pid, code)
    stored = set(keys or ())
    effective = panel_effective_keys_for_profile(code, stored)
    panel_keys = sorted((effective | stored) & set(GRANTABLE_USER_OVERRIDE_KEYS))
    flags = profile_flags(prof)
    editable = (
        flags["editable"]
        and can_manage_role_profiles(session)
        and role_profile_admin_enabled()
    )
    return jsonify({
        "profile": prof,
        "permissions": sorted(stored),
        "panel_permissions": panel_keys,
        "locked": flags["locked"],
        "editable": editable,
        "admin_enabled": role_profile_admin_enabled(),
        "leadership_defaults_applied": (prof.get("code") or code) in ("college_dean", "academic_vice_dean"),
    })


def _replace_profile_permissions(conn, profile_id: int, keys: set[str]) -> None:
    cur = conn.cursor()
    for k in keys:
        _ensure_permission_definition(conn, k)
    cur.execute("DELETE FROM role_profile_permissions WHERE profile_id = ?", (int(profile_id),))
    for k in sorted(keys):
        cur.execute(
            """
            INSERT INTO role_profile_permissions (profile_id, permission_key, granted)
            VALUES (?, ?, 1)
            ON CONFLICT(profile_id, permission_key) DO UPDATE SET granted = 1
            """,
            (int(profile_id), k),
        )


@role_profiles_bp.route("/<code>/permissions", methods=["PUT"])
@role_required("system_admin", "admin_main")
def put_profile_permissions(code: str):
    """استبدال صلاحيات قالب غير مقفول من كتالوج الصلاحيات الكامل."""
    data = request.get_json(force=True) or {}
    keys_in = data.get("permission_keys")
    if keys_in is None:
        keys_in = data.get("permissions")
    if not isinstance(keys_in, list):
        return jsonify({"status": "error", "message": "permission_keys يجب أن تكون قائمة"}), 400

    actor = (session.get("user") or "").strip() or "system"
    with get_connection() as conn:
        from backend.boot.role_profiles_seed import ensure_role_profile_tables, _is_pg

        ensure_role_profile_tables(conn, pg=_is_pg(conn))
        prof = get_profile_by_code(code, conn=conn)
        ok, err = assert_profile_editable(session, prof)
        if not ok:
            status = 404 if err == "القالب غير موجود." else 403
            return jsonify({"status": "error", "message": err or "غير مسموح"}), status
        pid = int(prof["id"])
        before = load_profile_permission_keys(conn, pid, code)
        final_keys = sanitize_permission_keys(keys_in)
        _replace_profile_permissions(conn, pid, final_keys)
        conn.commit()
        log_activity(
            action="role_profile.permissions_updated",
            details=(
                f"code={code}; before={len(before or [])}; after={len(final_keys)}; "
                f"sample={','.join(sorted(final_keys)[:12])}"
            ),
            actor=actor,
        )
        logger.info("PUT profile permissions code=%s keys=%s actor=%s", code, len(final_keys), actor)

    return jsonify({
        "status": "ok",
        "profile_code": code,
        "permissions": sorted(final_keys),
        "message": "تم حفظ صلاحيات القالب",
    }), 200


@role_profiles_bp.route("", methods=["POST"])
@role_required("system_admin", "admin_main")
def create_profile():
    """إنشاء قالب مخصص فوق دور أساسي مسموح."""
    data = request.get_json(force=True) or {}
    code = (data.get("code") or "").strip().lower()
    name_ar = (data.get("name_ar") or "").strip()
    base_role = (data.get("base_role") or "").strip().lower()
    scope_mode = normalize_scope_mode(data.get("scope_mode"))
    description_ar = (data.get("description_ar") or "").strip() or None
    keys_in = data.get("permission_keys") if isinstance(data.get("permission_keys"), list) else data.get("permissions")
    if not name_ar:
        return jsonify({"status": "error", "message": "name_ar مطلوب"}), 400
    ok, err = assert_profile_creatable(session, code=code, base_role=base_role)
    if not ok:
        return jsonify({"status": "error", "message": err or "غير مسموح"}), 400

    actor = (session.get("user") or "").strip() or "system"
    final_keys = sanitize_permission_keys(keys_in or [])
    with get_connection() as conn:
        from backend.boot.role_profiles_seed import ensure_role_profile_tables, _is_pg

        ensure_role_profile_tables(conn, pg=_is_pg(conn))
        cur = conn.cursor()
        exists = cur.execute("SELECT 1 FROM role_profiles WHERE code = ? LIMIT 1", (code,)).fetchone()
        if exists:
            return jsonify({"status": "error", "message": "رمز القالب مستخدم مسبقاً"}), 409
        cur.execute(
            """
            INSERT INTO role_profiles
            (code, name_ar, base_role, scope_mode, is_system, description_ar, default_home_path, is_active)
            VALUES (?, ?, ?, ?, 0, ?, NULL, 1)
            """,
            (code, name_ar, base_role, scope_mode, description_ar),
        )
        row = cur.execute("SELECT id FROM role_profiles WHERE code = ?", (code,)).fetchone()
        pid = int(row[0] if not hasattr(row, "keys") else row["id"])
        if final_keys:
            _replace_profile_permissions(conn, pid, final_keys)
        conn.commit()
        log_activity(
            action="role_profile.created",
            details=f"code={code}; base_role={base_role}; keys={len(final_keys)}",
            actor=actor,
        )

    return jsonify({
        "status": "ok",
        "profile": {
            "id": pid,
            "code": code,
            "name_ar": name_ar,
            "base_role": base_role,
            "scope_mode": scope_mode,
            "is_system": 0,
            "is_active": 1,
            "description_ar": description_ar,
        },
        "permissions": sorted(final_keys),
        "message": "تم إنشاء القالب",
    }), 200


@role_profiles_bp.route("/<code>", methods=["PATCH"])
@role_required("system_admin", "admin_main")
def patch_profile(code: str):
    """تعديل بيانات قالب غير مقفول (بدون تغيير الرمز/الدور الأساسي)."""
    data = request.get_json(force=True) or {}
    actor = (session.get("user") or "").strip() or "system"
    with get_connection() as conn:
        from backend.boot.role_profiles_seed import ensure_role_profile_tables, _is_pg

        ensure_role_profile_tables(conn, pg=_is_pg(conn))
        prof = get_profile_by_code(code, conn=conn)
        ok, err = assert_profile_editable(session, prof)
        if not ok:
            status = 404 if err == "القالب غير موجود." else 403
            return jsonify({"status": "error", "message": err or "غير مسموح"}), status
        name_ar = (data.get("name_ar") if "name_ar" in data else prof.get("name_ar") or "").strip()
        description_ar = data.get("description_ar") if "description_ar" in data else prof.get("description_ar")
        if description_ar is not None:
            description_ar = str(description_ar).strip() or None
        scope_mode = normalize_scope_mode(
            data.get("scope_mode") if "scope_mode" in data else prof.get("scope_mode")
        )
        if not name_ar:
            return jsonify({"status": "error", "message": "name_ar مطلوب"}), 400
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE role_profiles
            SET name_ar = ?, description_ar = ?, scope_mode = ?
            WHERE code = ?
            """,
            (name_ar, description_ar, scope_mode, code),
        )
        conn.commit()
        log_activity(
            action="role_profile.updated",
            details=f"code={code}; name_ar={name_ar}; scope_mode={scope_mode}",
            actor=actor,
        )
        updated = get_profile_by_code(code, conn=conn)
    return jsonify({"status": "ok", "profile": updated, "message": "تم تحديث القالب"}), 200


@role_profiles_bp.route("/<code>/archive", methods=["POST"])
@role_required("system_admin", "admin_main")
def archive_profile(code: str):
    """أرشفة منطقية لقالب غير مقفول."""
    data = request.get_json(silent=True) or {}
    activate = _as_bool(data.get("activate"), False)
    actor = (session.get("user") or "").strip() or "system"
    with get_connection() as conn:
        from backend.boot.role_profiles_seed import ensure_role_profile_tables, _is_pg

        ensure_role_profile_tables(conn, pg=_is_pg(conn))
        prof = get_profile_by_code(code, conn=conn)
        ok, err = assert_profile_editable(session, prof)
        if not ok:
            status = 404 if err == "القالب غير موجود." else 403
            return jsonify({"status": "error", "message": err or "غير مسموح"}), status
        cur = conn.cursor()
        cur.execute(
            "UPDATE role_profiles SET is_active = ? WHERE code = ?",
            (1 if activate else 0, code),
        )
        conn.commit()
        log_activity(
            action="role_profile.archived" if not activate else "role_profile.updated",
            details=f"code={code}; is_active={1 if activate else 0}",
            actor=actor,
        )
        updated = get_profile_by_code(code, conn=conn)
    return jsonify({
        "status": "ok",
        "profile": updated,
        "message": "تم تفعيل القالب" if activate else "تم أرشفة القالب",
    }), 200


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

        if transfer_office and _source_office_profile_inactive(conn, src):
            return jsonify({
                "status": "error",
                "message": "لا يمكن نقل قالب مؤرشف كمنصب — انقل الاستثناءات فقط أو فعّل القالب أولاً",
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

    from backend.core.permissions import GRANTABLE_USER_OVERRIDE_KEYS, PERMISSION_CATALOG

    label_by_key = {p["key"]: p.get("label_ar") or p["key"] for p in PERMISSION_CATALOG}
    grantable = [
        {"key": k, "label_ar": label_by_key.get(k, k)}
        for k in sorted(GRANTABLE_USER_OVERRIDE_KEYS)
    ]
    return jsonify({
        "status": "ok",
        "username": username,
        "role": tgt.get("role"),
        "grants": sorted(grants),
        "denies": sorted(denies),
        "can_add_department_users": CAN_ADD_DEPARTMENT_USERS in grants
        and CAN_ADD_DEPARTMENT_USERS not in denies,
        "grantable_override_keys": grantable,
    })


@role_profiles_bp.route("/profile_permissions", methods=["POST"])
@role_required("admin_main", "system_admin")
def save_profile_permissions():
    """توافق قديم: يوجّه إلى استبدال صلاحيات القالب الكامل."""
    data = request.get_json(force=True) or {}
    code = (data.get("profile_code") or data.get("code") or "").strip()
    keys_in = data.get("permission_keys")
    if keys_in is None:
        keys_in = data.get("permissions")
    if not code:
        return jsonify({"status": "error", "message": "profile_code مطلوب"}), 400
    if not isinstance(keys_in, list):
        return jsonify({"status": "error", "message": "permissions يجب أن تكون قائمة"}), 400
    # إعادة استخدام مسار PUT
    with get_connection() as conn:
        from backend.boot.role_profiles_seed import ensure_role_profile_tables, _is_pg

        ensure_role_profile_tables(conn, pg=_is_pg(conn))
        prof = get_profile_by_code(code, conn=conn)
        ok, err = assert_profile_editable(session, prof)
        if not ok:
            status = 404 if (err or "").startswith("القالب غير موجود") else 403
            return jsonify({"status": "error", "message": err or "غير مسموح"}), status
        pid = int(prof["id"])
        before = load_profile_permission_keys(conn, pid, code)
        final_keys = sanitize_permission_keys(keys_in)
        _replace_profile_permissions(conn, pid, final_keys)
        conn.commit()
        actor = (session.get("user") or "").strip() or "system"
        log_activity(
            action="role_profile.permissions_updated",
            details=(
                f"code={code}; before={len(before or [])}; after={len(final_keys)}; "
                f"sample={','.join(sorted(final_keys)[:12])}"
            ),
            actor=actor,
        )
    return jsonify({
        "status": "ok",
        "profile_code": code,
        "permissions": sorted(final_keys),
        "message": "تم حفظ صلاحيات القالب",
    }), 200


@role_profiles_bp.route("/user_overrides", methods=["POST"])
@role_required("system_admin", "college_dean", "admin_main")
def set_user_override():
    """منح أو إلغاء صلاحية إضافية لحساب معيّن."""
    from backend.core.permissions import (
        CAN_ADD_DEPARTMENT_USERS,
        GRANTABLE_USER_OVERRIDE_KEYS,
    )
    from backend.core.user_admin_policy import can_grant_hod_department_users_session
    from backend.core.auth_roles import _normalize_role

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
    from backend.core.permissions import FORBIDDEN_USER_OVERRIDE_KEYS

    if permission_key in FORBIDDEN_USER_OVERRIDE_KEYS:
        return jsonify({"status": "error", "message": "صلاحية حساسة لا تُمنح كاستثناء فردي"}), 400
    if permission_key not in GRANTABLE_USER_OVERRIDE_KEYS:
        return jsonify({"status": "error", "message": "صلاحية غير مسموح منحها من هنا"}), 400

    actor_role = _normalize_role(session.get("user_role") or "")
    is_principal = is_principal_admin_session(session) or actor_role in ("admin_main", "system_admin")
    # العميد يبقى قادراً على منح إضافة مستخدمي القسم فقط؛ باقي المفاتيح للأدمن الرئيسي
    if permission_key == CAN_ADD_DEPARTMENT_USERS:
        if not can_grant_hod_department_users_session(session):
            return jsonify({"status": "error", "message": "غير مسموح"}), 403
    elif not is_principal:
        return jsonify({"status": "error", "message": "منح هذه الصلاحية محصور على الأدمن الرئيسي"}), 403

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
            # سحب المنح: احذف صف المنح؛ للرفض الصريح استخدم granted=0 عند الحاجة
            cur.execute(
                """
                DELETE FROM user_permission_overrides
                WHERE lower(username) = lower(?) AND permission_key = ?
                """,
                (username, permission_key),
            )
            if data.get("deny") in (True, 1, "1", "true", "True"):
                cur.execute(
                    """
                    INSERT INTO user_permission_overrides (username, permission_key, granted)
                    VALUES (?, ?, 0)
                    ON CONFLICT(username, permission_key) DO UPDATE SET granted = 0
                    """,
                    (tgt.get("username") or username, permission_key),
                )
        conn.commit()
        log_activity(
            action="user_override.set" if granted else "user_override.clear",
            details=f"username={username}; key={permission_key}; granted={int(granted)}",
            actor=actor,
        )
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
