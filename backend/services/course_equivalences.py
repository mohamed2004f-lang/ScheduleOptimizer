"""API إدارة مجموعات تكافؤ المقررات بين الأقسام."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.core.auth import login_required, role_required
from backend.repositories import course_equivalence_repo as cer
from .utilities import get_connection

course_equivalence_bp = Blueprint("course_equivalence", __name__, url_prefix="/course_equivalences")

_ADMIN_ROLES = ("admin", "admin_main")


@course_equivalence_bp.route("/groups", methods=["GET"])
@login_required
def list_equivalence_groups():
    with get_connection() as conn:
        groups = cer.list_groups(conn)
        return jsonify({"status": "ok", "groups": groups})


@course_equivalence_bp.route("/groups/<int:group_id>/items", methods=["GET"])
@login_required
def list_equivalence_items(group_id: int):
    with get_connection() as conn:
        items = cer.list_items_for_group(conn, group_id)
        return jsonify({"status": "ok", "items": items})


@course_equivalence_bp.route("/group/save", methods=["POST"])
@role_required(*_ADMIN_ROLES)
def save_equivalence_group():
    data = request.get_json(force=True) or {}
    group_key = (data.get("group_key") or "").strip()
    title = data.get("title")
    is_active = bool(data.get("is_active", True))
    if not group_key:
        return jsonify({"status": "error", "message": "group_key مطلوب"}), 400
    try:
        with get_connection() as conn:
            gid = cer.save_group(conn, group_key=group_key, title=title, is_active=is_active)
            conn.commit()
        return jsonify({"status": "ok", "id": gid})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@course_equivalence_bp.route("/item/save", methods=["POST"])
@role_required(*_ADMIN_ROLES)
def save_equivalence_item():
    data = request.get_json(force=True) or {}
    try:
        gid = int(data.get("group_id"))
        did = int(data.get("department_id"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "group_id و department_id مطلوبان"}), 400
    course_name = data.get("course_name")
    course_code = data.get("course_code")
    pc = data.get("program_course_id")
    try:
        pc_i = int(pc) if pc not in (None, "") else None
    except (TypeError, ValueError):
        pc_i = None
    is_active = bool(data.get("is_active", True))
    try:
        with get_connection() as conn:
            cer.save_item(
                conn,
                group_id=gid,
                department_id=did,
                course_name=str(course_name or ""),
                course_code=course_code,
                program_course_id=pc_i,
                is_active=is_active,
            )
            conn.commit()
        return jsonify({"status": "ok"})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@course_equivalence_bp.route("/item/delete", methods=["POST"])
@role_required(*_ADMIN_ROLES)
def delete_equivalence_item():
    data = request.get_json(force=True) or {}
    try:
        item_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "id مطلوب"}), 400
    with get_connection() as conn:
        ok = cer.delete_item(conn, item_id)
        conn.commit()
    if not ok:
        return jsonify({"status": "error", "message": "العنصر غير موجود"}), 404
    return jsonify({"status": "ok"})


@course_equivalence_bp.route("/group/delete", methods=["POST"])
@role_required(*_ADMIN_ROLES)
def delete_equivalence_group():
    data = request.get_json(force=True) or {}
    try:
        group_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "id مطلوب"}), 400
    with get_connection() as conn:
        ok = cer.delete_group(conn, group_id)
        conn.commit()
    if not ok:
        return jsonify({"status": "error", "message": "المجموعة غير موجودة"}), 404
    return jsonify({"status": "ok"})
