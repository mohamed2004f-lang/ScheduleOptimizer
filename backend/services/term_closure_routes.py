"""مسارات لوحة إغلاق الفصل الموحّد."""

from __future__ import annotations

import os

from flask import jsonify, request, send_file, session, render_template

from backend.core.auth import (
    _normalize_role,
    login_required,
    role_required,
)
from backend.core.department_scope_policy import (
    head_home_department_id,
    resolve_effective_department_scope_id,
)
from backend.services.quality_metrics import term_label_from_conn
from backend.services.term_closure import (
    ALL_STAGES,
    REQUIRED_FOR_ARCHIVE,
    _upsert_term_closure,
    build_term_archive_zip,
    close_term_stage,
    get_term_closure_row,
    get_term_closure_status,
    reopen_term_stage,
    term_archive_dir,
)
from backend.services.utilities import get_connection

_TERM_CLOSURE_ROLES = (
    "admin",
    "admin_main",
    "system_admin",
    "college_dean",
    "academic_vice_dean",
    "head_of_department",
)


def _actor() -> str:
    return (session.get("user") or session.get("username") or "").strip()


def _resolve_department_id(conn, data: dict | None = None) -> int | None:
    data = data or {}
    raw = data.get("department_id")
    if raw is not None and str(raw).strip() != "":
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    q = request.args.get("department_id")
    if q not in (None, ""):
        try:
            return int(q)
        except (TypeError, ValueError):
            pass

    uname = _actor()
    scoped = resolve_effective_department_scope_id(conn, uname)
    if scoped is not None:
        return int(scoped)
    role = _normalize_role((session.get("user_role") or "").strip())
    if role == "head_of_department":
        hid = head_home_department_id(conn, uname)
        if hid is not None:
            return int(hid)
    return None


def register_term_closure_routes(bp) -> None:
    @bp.route("/term_closure")
    @login_required
    @role_required(*_TERM_CLOSURE_ROLES)
    def term_closure_page():
        return render_template("term_closure.html", active_page="term_closure")

    @bp.route("/term_closure/status", methods=["GET"])
    @login_required
    @role_required(*_TERM_CLOSURE_ROLES)
    def term_closure_status_api():
        with get_connection() as conn:
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _resolve_department_id(conn)
            payload = get_term_closure_status(
                conn, semester=sem, department_id=dept_id
            )
        return jsonify(payload), 200

    @bp.route("/term_closure/close_stage", methods=["POST"])
    @login_required
    @role_required(*_TERM_CLOSURE_ROLES)
    def term_closure_close_stage_api():
        data = request.get_json(force=True) or {}
        stage = (data.get("stage") or "").strip().lower()
        if stage not in ALL_STAGES:
            return jsonify(
                {
                    "status": "error",
                    "message": f"مرحلة غير معروفة. المسموح: {', '.join(ALL_STAGES)}",
                }
            ), 400
        force = str(data.get("force") or "").lower() in ("1", "true", "yes")
        note = (data.get("note") or "").strip()
        with get_connection() as conn:
            sem = (data.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _resolve_department_id(conn, data)
            try:
                result = close_term_stage(
                    conn,
                    stage=stage,
                    semester=sem,
                    department_id=dept_id,
                    actor=_actor(),
                    force=force,
                    note=note,
                    build_archive=True,
                )
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400
            except Exception as exc:
                return jsonify({"status": "error", "message": str(exc)}), 500
        return jsonify(result), 200

    @bp.route("/term_closure/reopen_stage", methods=["POST"])
    @login_required
    @role_required(
        "admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean"
    )
    def term_closure_reopen_stage_api():
        data = request.get_json(force=True) or {}
        stage = (data.get("stage") or "").strip().lower()
        reason = (data.get("reason") or "").strip()
        with get_connection() as conn:
            sem = (data.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _resolve_department_id(conn, data)
            try:
                result = reopen_term_stage(
                    conn,
                    stage=stage,
                    semester=sem,
                    department_id=dept_id,
                    actor=_actor(),
                    reason=reason,
                )
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify(result), 200

    @bp.route("/term_closure/build_archive", methods=["POST"])
    @login_required
    @role_required(*_TERM_CLOSURE_ROLES)
    def term_closure_build_archive_api():
        data = request.get_json(force=True) or {}
        with get_connection() as conn:
            sem = (data.get("semester") or "").strip() or term_label_from_conn(conn)
            dept_id = _resolve_department_id(conn, data)
            row = get_term_closure_row(conn, sem, dept_id)
            stages = (row or {}).get("stages") or {}
            missing = [
                s
                for s in REQUIRED_FOR_ARCHIVE
                if not (stages.get(s) or {}).get("closed")
            ]
            if missing:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "لا يمكن بناء الأرشيف قبل إغلاق المراحل: "
                            + ", ".join(missing),
                        }
                    ),
                    400,
                )
            arch = build_term_archive_zip(
                conn,
                semester=sem,
                department_id=dept_id,
                actor=_actor(),
                stages=stages,
            )
            _upsert_term_closure(
                conn,
                semester=sem,
                department_id=dept_id,
                stages=stages,
                actor=_actor(),
                archive_filename=arch.get("archive_filename") or "",
                archive_built_at=arch.get("archive_built_at") or "",
                closed_at=arch.get("archive_built_at") or "",
                closed_by=_actor(),
            )
            result = get_term_closure_status(
                conn, semester=sem, department_id=dept_id
            )
            result["built"] = arch
        return jsonify(result), 200

    @bp.route("/term_closure/archives/<path:filename>")
    @login_required
    @role_required(*_TERM_CLOSURE_ROLES)
    def term_closure_download_archive(filename: str):
        safe = os.path.basename((filename or "").strip())
        if not safe or safe != os.path.basename(filename):
            return jsonify({"status": "error", "message": "اسم ملف غير صالح"}), 400
        path = os.path.join(term_archive_dir(), safe)
        if not os.path.isfile(path):
            return jsonify({"status": "error", "message": "الملف غير موجود"}), 404
        return send_file(
            path,
            mimetype="application/zip",
            as_attachment=True,
            download_name=safe,
        )
