"""API سجل المقررات المشتركة بين الأقسام."""
from __future__ import annotations

import io

from flask import jsonify, request, send_file, session

from backend.core.auth import login_required, role_required
from backend.core.college_shared_catalog import (
    SHARE_TYPE_LABELS,
    build_import_template_bytes,
    delete_catalog_entry,
    get_catalog_entry,
    import_catalog_workbook,
    list_catalog_entries,
    list_specialty_departments,
    save_catalog_entry,
    set_catalog_active,
    sync_catalog_entry,
)
from backend.core.department_scope_policy import can_manage_college_shared_catalog
from backend.services.utilities import get_connection

_ADMIN_FULL = ("admin", "admin_main", "system_admin", "college_dean")
_SHARED_WRITE = (
    "admin",
    "admin_main",
    "system_admin",
    "college_dean",
    "academic_vice_dean",
)
_PLAN_VIEW = (
    "admin",
    "admin_main",
    "system_admin",
    "college_dean",
    "academic_vice_dean",
    "head_of_department",
)


def _forbid_shared_catalog_write(conn):
    actor = (session.get("user") or session.get("username") or "").strip()
    role = (session.get("user_role") or "").strip()
    if not can_manage_college_shared_catalog(conn, actor, user_role=role):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": (
                        "تعديل سجل المقررات المشتركة مسموح للأدمن الرئيسي "
                        "أو عميد الكلية أو وكيلة الشؤون العلمية فقط."
                    ),
                }
            ),
            403,
        )
    return None


def register_shared_catalog_routes(bp) -> None:
    @bp.route("/shared_catalog/meta", methods=["GET"])
    @login_required
    @role_required(*_PLAN_VIEW)
    def shared_catalog_meta():
        return jsonify(
            {
                "status": "ok",
                "share_types": [
                    {"value": k, "label": v} for k, v in SHARE_TYPE_LABELS.items()
                ],
            }
        )

    @bp.route("/shared_catalog/list", methods=["GET"])
    @login_required
    @role_required(*_PLAN_VIEW)
    def shared_catalog_list():
        include_inactive = (request.args.get("include_inactive") or "").strip() in (
            "1",
            "true",
            "yes",
        )
        with get_connection() as conn:
            items = list_catalog_entries(conn, include_inactive=include_inactive)
        return jsonify({"status": "ok", "items": items})

    @bp.route("/shared_catalog/departments", methods=["GET"])
    @login_required
    @role_required(*_PLAN_VIEW)
    def shared_catalog_departments():
        with get_connection() as conn:
            deps = list_specialty_departments(conn)
        return jsonify({"status": "ok", "departments": deps})

    @bp.route("/shared_catalog/get/<int:catalog_id>", methods=["GET"])
    @login_required
    @role_required(*_PLAN_VIEW)
    def shared_catalog_get(catalog_id: int):
        with get_connection() as conn:
            entry = get_catalog_entry(conn, int(catalog_id))
        if not entry:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        return jsonify({"status": "ok", "entry": entry})

    @bp.route("/shared_catalog/save", methods=["POST"])
    @login_required
    @role_required(*_SHARED_WRITE)
    def shared_catalog_save():
        body = request.get_json(force=True, silent=True) or {}
        try:
            with get_connection() as conn:
                denied = _forbid_shared_catalog_write(conn)
                if denied:
                    return denied
                result = save_catalog_entry(conn, body)
                conn.commit()
                try:
                    from backend.core.cache_setup import invalidate_list_prefix

                    invalidate_list_prefix("courses")
                except Exception:
                    pass
            return jsonify({"status": "ok", **result}), 200
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    @bp.route("/shared_catalog/sync/<int:catalog_id>", methods=["POST"])
    @login_required
    @role_required(*_SHARED_WRITE)
    def shared_catalog_sync(catalog_id: int):
        try:
            with get_connection() as conn:
                denied = _forbid_shared_catalog_write(conn)
                if denied:
                    return denied
                sync_result = sync_catalog_entry(conn, int(catalog_id))
                conn.commit()
            return jsonify({"status": "ok", "sync": sync_result}), 200
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    @bp.route("/shared_catalog/set_active", methods=["POST"])
    @login_required
    @role_required(*_SHARED_WRITE)
    def shared_catalog_set_active():
        body = request.get_json(force=True, silent=True) or {}
        try:
            cid = int(body.get("id"))
            active = bool(body.get("is_active", True))
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "id مطلوب"}), 400
        try:
            with get_connection() as conn:
                denied = _forbid_shared_catalog_write(conn)
                if denied:
                    return denied
                set_catalog_active(conn, cid, active=active)
                conn.commit()
            return jsonify({"status": "ok"}), 200
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    @bp.route("/shared_catalog/delete", methods=["POST"])
    @login_required
    @role_required(*_SHARED_WRITE)
    def shared_catalog_delete():
        body = request.get_json(force=True, silent=True) or {}
        try:
            cid = int(body.get("id"))
            force = bool(body.get("force", False))
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "id مطلوب"}), 400
        try:
            with get_connection() as conn:
                denied = _forbid_shared_catalog_write(conn)
                if denied:
                    return denied
                delete_catalog_entry(conn, cid, force=force)
                conn.commit()
            return jsonify({"status": "ok", "deleted": True}), 200
        except ValueError as e:
            with get_connection() as conn:
                conn.commit()
            return jsonify({"status": "ok", "deactivated": True, "message": str(e)}), 200

    @bp.route("/shared_catalog/import/template", methods=["GET"])
    @login_required
    @role_required(*_SHARED_WRITE)
    def shared_catalog_import_template():
        with get_connection() as conn:
            denied = _forbid_shared_catalog_write(conn)
            if denied:
                return denied
        data = build_import_template_bytes()
        return send_file(
            io.BytesIO(data),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="college_shared_courses_template.xlsx",
        )

    @bp.route("/shared_catalog/import/excel", methods=["POST"])
    @login_required
    @role_required(*_SHARED_WRITE)
    def shared_catalog_import_excel():
        f = request.files.get("file")
        if not f:
            return jsonify({"status": "error", "message": "file required"}), 400
        try:
            with get_connection() as conn:
                denied = _forbid_shared_catalog_write(conn)
                if denied:
                    return denied
                result = import_catalog_workbook(conn, f)
                conn.commit()
                try:
                    from backend.core.cache_setup import invalidate_list_prefix

                    invalidate_list_prefix("courses")
                except Exception:
                    pass
            return jsonify({"status": "ok", **result}), 200
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
