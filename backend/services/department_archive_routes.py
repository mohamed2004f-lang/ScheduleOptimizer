"""مسارات أرشيف القسم + الدليل + المساعد الذكي."""

from __future__ import annotations

from typing import Any

from flask import jsonify, render_template, request, send_file, session

from backend.core.auth import role_required
from backend.core.department_archive_catalog import ARCHIVE_RECORD_TYPES, DRAFT_TEMPLATES
from backend.services.department_archive import (
    archive_checklist,
    catalog_payload,
    create_archive_item,
    ensure_department_archive_table,
    get_archive_item,
    link_archive_item_to_evidence,
    list_archive_items,
    soft_delete_archive_item,
    suggest_qaa_for_item,
)
from backend.services.department_archive_assistant import run_assistant
from backend.services.quality_metrics import term_label_from_conn
from backend.services.utilities import get_connection


def _actor() -> str:
    return (session.get("user") or "").strip()


def _dept_scope(conn) -> int | None:
    from backend.services.academic_quality import _resolve_department_scope

    return _resolve_department_scope(conn)


def _parse_dept_id(conn, raw: Any = None) -> int:
    scoped = _dept_scope(conn)
    if scoped is not None:
        return int(scoped)
    if raw in (None, "", "null"):
        raw = request.args.get("department_id") or (request.form.get("department_id") if request.form else None)
    if raw in (None, "", "null"):
        # افتراضي: أول قسم نشط للإدارة
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id FROM departments WHERE COALESCE(is_active, 1) = 1 ORDER BY code LIMIT 1"
        ).fetchone()
        if not row:
            raise ValueError("لا يوجد قسم نشط")
        return int(row[0] if not hasattr(row, "keys") else row["id"])
    return int(raw)


def _departments(conn) -> list[dict[str, Any]]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, code, name_ar FROM departments
        WHERE COALESCE(is_active, 1) = 1
        ORDER BY code
        """
    ).fetchall() or []
    out = []
    for r in rows:
        if hasattr(r, "keys"):
            out.append({"id": int(r["id"]), "code": r["code"], "name_ar": r["name_ar"] or r["code"]})
        else:
            out.append({"id": int(r[0]), "code": r[1], "name_ar": r[2] or r[1]})
    return out


def register_department_archive_routes(bp) -> None:
    roles = (
        "admin",
        "admin_main",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
        "head_of_department",
    )

    @bp.route("/archive", methods=["GET"])
    @role_required(*roles)
    def department_archive_page():
        with get_connection() as conn:
            ensure_department_archive_table(conn)
            semester = (request.args.get("semester") or term_label_from_conn(conn) or "").strip()
            try:
                dept_id = _parse_dept_id(conn, request.args.get("department_id"))
            except ValueError as e:
                return render_template(
                    "department_archive.html",
                    page_error=str(e),
                    catalog=catalog_payload(),
                    departments=[],
                    items=[],
                    checklist=None,
                    department_id=None,
                    semester=semester,
                    scoped_locked=False,
                )
            scoped = _dept_scope(conn)
            depts = _departments(conn)
            if scoped is not None:
                depts = [d for d in depts if d["id"] == int(scoped)]
            items = list_archive_items(conn, department_id=dept_id, semester=semester or None)
            checklist = archive_checklist(conn, department_id=dept_id, semester=semester)
            dept_name = next((d["name_ar"] for d in depts if d["id"] == dept_id), f"قسم #{dept_id}")
        return render_template(
            "department_archive.html",
            page_error=None,
            catalog=catalog_payload(),
            departments=depts,
            items=items,
            checklist=checklist,
            department_id=dept_id,
            department_name_ar=dept_name,
            semester=semester,
            scoped_locked=scoped is not None,
            record_types=list(ARCHIVE_RECORD_TYPES.values()),
        )

    @bp.route("/archive/guide", methods=["GET"])
    @role_required(*roles)
    def department_archive_guide_page():
        return render_template(
            "department_archive_guide.html",
            catalog=catalog_payload(),
            record_types=list(ARCHIVE_RECORD_TYPES.values()),
            drafts=DRAFT_TEMPLATES,
        )

    @bp.route("/api/archive/catalog", methods=["GET"])
    @role_required(*roles)
    def archive_catalog_api():
        return jsonify({"status": "ok", **catalog_payload()}), 200

    @bp.route("/api/archive/items", methods=["GET"])
    @role_required(*roles)
    def archive_items_list():
        with get_connection() as conn:
            dept_id = _parse_dept_id(conn, request.args.get("department_id"))
            items = list_archive_items(
                conn,
                department_id=dept_id,
                semester=(request.args.get("semester") or "").strip() or None,
                record_type=(request.args.get("record_type") or "").strip() or None,
                q=(request.args.get("q") or "").strip() or None,
            )
        return jsonify({"status": "ok", "items": items, "department_id": dept_id}), 200

    @bp.route("/api/archive/items", methods=["POST"])
    @role_required(*roles)
    def archive_items_create():
        data = request.get_json(silent=True) or {}
        # دعم multipart للرفع
        if request.content_type and "multipart/form-data" in request.content_type:
            data = {k: request.form.get(k) for k in request.form.keys()}
        try:
            with get_connection() as conn:
                dept_id = _parse_dept_id(conn, data.get("department_id"))
                raw = None
                oname = ""
                mime = ""
                f = request.files.get("file") if request.files else None
                if f and f.filename:
                    raw = f.read()
                    oname = f.filename
                    mime = f.mimetype or ""
                item = create_archive_item(
                    conn,
                    department_id=dept_id,
                    record_type=str(data.get("record_type") or ""),
                    title_ar=str(data.get("title_ar") or ""),
                    actor=_actor(),
                    program_id=int(data["program_id"]) if data.get("program_id") not in (None, "", "null") else None,
                    ref_number=str(data.get("ref_number") or ""),
                    doc_date=str(data.get("doc_date") or ""),
                    semester=str(data.get("semester") or "") or None,
                    party_ar=str(data.get("party_ar") or ""),
                    tags=str(data.get("tags") or ""),
                    body_text=str(data.get("body_text") or ""),
                    follow_up_status=str(data.get("follow_up_status") or "na"),
                    raw=raw,
                    original_name=oname,
                    mime_type=mime,
                )
            return jsonify({"status": "ok", "item": item}), 200
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    @bp.route("/api/archive/items/<int:item_id>", methods=["DELETE"])
    @role_required(*roles)
    def archive_items_delete(item_id: int):
        with get_connection() as conn:
            item = get_archive_item(conn, item_id)
            if not item:
                return jsonify({"status": "error", "message": "غير موجود"}), 404
            scoped = _dept_scope(conn)
            if scoped is not None and int(item["department_id"]) != int(scoped):
                return jsonify({"status": "error", "message": "خارج نطاق قسمك"}), 403
            soft_delete_archive_item(conn, item_id, actor=_actor())
        return jsonify({"status": "ok"}), 200

    @bp.route("/api/archive/file/<int:item_id>", methods=["GET"])
    @role_required(*roles)
    def archive_file_download(item_id: int):
        import os

        with get_connection() as conn:
            item = get_archive_item(conn, item_id)
            if not item:
                return jsonify({"status": "error", "message": "غير موجود"}), 404
            scoped = _dept_scope(conn)
            if scoped is not None and int(item["department_id"]) != int(scoped):
                return jsonify({"status": "error", "message": "خارج نطاق قسمك"}), 403
            path = (item.get("stored_path") or "").strip()
            if not path or not os.path.isfile(path):
                return jsonify({"status": "error", "message": "لا يوجد ملف"}), 404
            return send_file(
                path,
                as_attachment=True,
                download_name=item.get("original_name") or os.path.basename(path),
            )

    @bp.route("/api/archive/checklist", methods=["GET"])
    @role_required(*roles)
    def archive_checklist_api():
        with get_connection() as conn:
            dept_id = _parse_dept_id(conn, request.args.get("department_id"))
            sem = (request.args.get("semester") or term_label_from_conn(conn) or "").strip()
            data = archive_checklist(conn, department_id=dept_id, semester=sem)
        return jsonify(data), 200

    @bp.route("/api/archive/suggest_qaa/<int:item_id>", methods=["GET"])
    @role_required(*roles)
    def archive_suggest_qaa(item_id: int):
        try:
            with get_connection() as conn:
                data = suggest_qaa_for_item(conn, item_id)
            return jsonify(data), 200
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 404

    @bp.route("/api/archive/link_evidence", methods=["POST"])
    @role_required(*roles)
    def archive_link_evidence():
        data = request.get_json(force=True) or {}
        try:
            with get_connection() as conn:
                item_id = int(data.get("item_id") or 0)
                item = get_archive_item(conn, item_id)
                if not item:
                    return jsonify({"status": "error", "message": "السجل غير موجود"}), 404
                scoped = _dept_scope(conn)
                if scoped is not None and int(item["department_id"]) != int(scoped):
                    return jsonify({"status": "error", "message": "خارج نطاق قسمك"}), 403
                result = link_archive_item_to_evidence(
                    conn,
                    item_id=item_id,
                    indicator_code=str(data.get("indicator_code") or ""),
                    catalog_version=str(data.get("catalog_version") or ""),
                    actor=_actor(),
                    semester=str(data.get("semester") or "") or None,
                )
            return jsonify(result), 200
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    @bp.route("/api/archive/templates/<record_type>", methods=["GET"])
    @role_required(*roles)
    def archive_template_download(record_type: str):
        from backend.services.department_archive_assistant import draft_archive_document

        try:
            draft = draft_archive_document(
                record_type=record_type,
                fields={
                    "title_ar": request.args.get("title_ar") or "موضوع الوثيقة",
                    "doc_date": request.args.get("doc_date") or "YYYY-MM-DD",
                    "ref_number": request.args.get("ref_number") or "—",
                    "party_ar": request.args.get("party_ar") or "—",
                    "body_text": request.args.get("body_text") or "…",
                },
                department_name_ar=request.args.get("department_name_ar") or "القسم",
            )
            from flask import Response

            return Response(
                draft["draft_text"],
                mimetype="text/plain; charset=utf-8",
                headers={
                    "Content-Disposition": f"attachment; filename=template_{record_type}.txt"
                },
            )
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    @bp.route("/api/archive/assistant", methods=["POST"])
    @role_required(*roles)
    def archive_assistant_api():
        data = request.get_json(force=True) or {}
        try:
            with get_connection() as conn:
                dept_raw = data.get("department_id")
                dept_id = None
                if data.get("intent") in ("gaps", "search") or dept_raw not in (None, "", "null"):
                    dept_id = _parse_dept_id(conn, dept_raw)
                result = run_assistant(
                    conn,
                    intent=str(data.get("intent") or "help"),
                    department_id=dept_id,
                    semester=str(data.get("semester") or "") or None,
                    title_ar=str(data.get("title_ar") or ""),
                    body_text=str(data.get("body_text") or ""),
                    filename=str(data.get("filename") or ""),
                    record_type=str(data.get("record_type") or ""),
                    fields=data.get("fields") if isinstance(data.get("fields"), dict) else None,
                    item_id=int(data["item_id"]) if data.get("item_id") not in (None, "", "null") else None,
                    department_name_ar=str(data.get("department_name_ar") or ""),
                    query=str(data.get("query") or ""),
                )
            return jsonify(result), 200
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
