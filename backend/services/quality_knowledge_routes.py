"""مسارات مكتبة معرفة مساعد الجودة."""

from __future__ import annotations

import io
from typing import Any

from flask import jsonify, render_template, request, send_file, session

from backend.core.auth import _normalize_role, role_required
from backend.services.quality_knowledge import (
    can_approve_knowledge,
    can_upload_knowledge,
    create_knowledge_doc,
    export_approved_knowledge_zip,
    get_knowledge_doc,
    library_bootstrap,
    list_knowledge_docs,
    retrieve_knowledge,
    seed_approved_global_refs_into_knowledge,
    seed_specialty_packs_into_knowledge,
    set_knowledge_status,
    soft_delete_knowledge_doc,
)
from backend.services.quality_metrics import term_label_from_conn
from backend.services.utilities import get_connection

_ROLES = (
    "admin",
    "admin_main",
    "system_admin",
    "college_dean",
    "academic_vice_dean",
    "head_of_department",
    "instructor",
)


def _actor() -> str:
    return (session.get("user") or "").strip()


def _role() -> str:
    return _normalize_role((session.get("user_role") or "").strip())


def _cq() -> bool:
    return int(session.get("is_college_quality_lead") or 0) == 1


def _dept_scope(conn) -> int | None:
    from backend.services.academic_quality import _resolve_department_scope

    return _resolve_department_scope(conn)


def _parse_dept(conn, raw: Any = None) -> int | None:
    scoped = _dept_scope(conn)
    if scoped is not None and _role() in ("head_of_department", "instructor"):
        return int(scoped)
    if raw in (None, "", "null"):
        raw = request.args.get("department_id")
        if raw in (None, "", "null") and request.is_json:
            raw = (request.get_json(silent=True) or {}).get("department_id")
        if raw in (None, "", "null") and request.form:
            raw = request.form.get("department_id")
    if raw in (None, "", "null"):
        return None
    return int(raw)


def _departments(conn) -> list[dict[str, Any]]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, code, name_ar FROM departments
        WHERE COALESCE(is_active, 1) = 1 ORDER BY code
        """
    ).fetchall() or []
    out = []
    for r in rows:
        if hasattr(r, "keys"):
            out.append({"id": int(r["id"]), "code": r["code"], "name_ar": r["name_ar"] or r["code"]})
        else:
            out.append({"id": int(r[0]), "code": r[1], "name_ar": r[2] or r[1]})
    return out


def register_quality_knowledge_routes(bp) -> None:
    @bp.route("/assistant/knowledge", methods=["GET"])
    @role_required(*_ROLES)
    def quality_knowledge_library_page():
        with get_connection() as conn:
            dept_id = _parse_dept(conn)
            boot = library_bootstrap(
                conn,
                role=_role(),
                is_college_quality_lead=_cq(),
                department_id=dept_id,
                seed_if_empty=True,
            )
            departments = _departments(conn)
            semester = term_label_from_conn(conn)
        return render_template(
            "quality_knowledge_library.html",
            bootstrap=boot,
            departments=departments,
            selected_department_id=dept_id,
            semester=semester,
            user_role=_role(),
        )

    @bp.route("/api/assistant/knowledge/bootstrap", methods=["GET"])
    @role_required(*_ROLES)
    def quality_knowledge_bootstrap_api():
        with get_connection() as conn:
            dept_id = _parse_dept(conn)
            return jsonify(
                library_bootstrap(
                    conn,
                    role=_role(),
                    is_college_quality_lead=_cq(),
                    department_id=dept_id,
                    seed_if_empty=True,
                )
            )

    @bp.route("/api/assistant/knowledge/docs", methods=["GET"])
    @role_required(*_ROLES)
    def quality_knowledge_list_api():
        with get_connection() as conn:
            docs = list_knowledge_docs(
                conn,
                department_id=_parse_dept(conn),
                status=(request.args.get("status") or "").strip() or None,
                category=(request.args.get("category") or "").strip() or None,
            )
        return jsonify({"status": "ok", "docs": docs})

    @bp.route("/api/assistant/knowledge/docs", methods=["POST"])
    @role_required(*_ROLES)
    def quality_knowledge_create_api():
        if not can_upload_knowledge(_role()):
            return jsonify({"status": "error", "message": "لا صلاحية لرفع وثائق المعرفة"}), 403
        try:
            with get_connection() as conn:
                dept_id = _parse_dept(conn)
                f = request.files.get("file")
                raw = None
                oname = ""
                mime = ""
                if f and f.filename:
                    raw = f.read()
                    oname = f.filename
                    mime = f.mimetype or ""
                # JSON body fallback
                data = {}
                if request.is_json:
                    data = request.get_json(silent=True) or {}
                title = (request.form.get("title_ar") or data.get("title_ar") or "").strip()
                body_text = (request.form.get("body_text") or data.get("body_text") or "").strip()
                status = (request.form.get("status") or data.get("status") or "draft").strip()
                if status == "approved" and not can_approve_knowledge(
                    _role(), is_college_quality_lead=_cq()
                ):
                    status = "pending_review"
                doc = create_knowledge_doc(
                    conn,
                    title_ar=title,
                    actor=_actor(),
                    category=(request.form.get("category") or data.get("category") or "other"),
                    department_id=dept_id
                    if dept_id is not None
                    else (
                        int(data["department_id"])
                        if data.get("department_id") not in (None, "", "null")
                        else None
                    ),
                    source_label_ar=(request.form.get("source_label_ar") or data.get("source_label_ar") or ""),
                    source_url=(request.form.get("source_url") or data.get("source_url") or ""),
                    notes_ar=(request.form.get("notes_ar") or data.get("notes_ar") or ""),
                    body_text=body_text,
                    raw=raw,
                    original_name=oname,
                    mime_type=mime,
                    status=status,
                )
            return jsonify({"status": "ok", "doc": doc})
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/assistant/knowledge/docs/<int:doc_id>", methods=["GET"])
    @role_required(*_ROLES)
    def quality_knowledge_get_api(doc_id: int):
        with get_connection() as conn:
            doc = get_knowledge_doc(conn, doc_id)
        if not doc:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        return jsonify({"status": "ok", "doc": doc})

    @bp.route("/api/assistant/knowledge/docs/<int:doc_id>/status", methods=["POST"])
    @role_required(*_ROLES)
    def quality_knowledge_status_api(doc_id: int):
        data = request.get_json(force=True) or {}
        st = (data.get("status") or "").strip()
        if st == "approved" and not can_approve_knowledge(_role(), is_college_quality_lead=_cq()):
            return jsonify({"status": "error", "message": "لا صلاحية لاعتماد الوثائق"}), 403
        if st != "approved" and not can_upload_knowledge(_role()):
            return jsonify({"status": "error", "message": "لا صلاحية لتغيير الحالة"}), 403
        try:
            with get_connection() as conn:
                doc = set_knowledge_status(conn, doc_id, status=st, actor=_actor())
            return jsonify({"status": "ok", "doc": doc})
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    @bp.route("/api/assistant/knowledge/docs/<int:doc_id>/delete", methods=["POST"])
    @role_required(*_ROLES)
    def quality_knowledge_delete_api(doc_id: int):
        if not can_upload_knowledge(_role()):
            return jsonify({"status": "error", "message": "لا صلاحية للحذف"}), 403
        with get_connection() as conn:
            soft_delete_knowledge_doc(conn, doc_id, actor=_actor())
        return jsonify({"status": "ok"})

    @bp.route("/api/assistant/knowledge/retrieve", methods=["POST"])
    @role_required(*_ROLES)
    def quality_knowledge_retrieve_api():
        data = request.get_json(force=True) or {}
        with get_connection() as conn:
            result = retrieve_knowledge(
                conn,
                query=(data.get("query") or data.get("notes") or "").strip(),
                department_id=_parse_dept(conn, data.get("department_id")),
                category=(data.get("category") or "").strip() or None,
                top_k=int(data.get("top_k") or 6),
                approved_only=bool(data.get("approved_only", True)),
            )
        return jsonify(result)

    @bp.route("/assistant/knowledge/export.zip", methods=["GET"])
    @role_required(*_ROLES)
    def quality_knowledge_export_zip():
        if not (
            can_upload_knowledge(_role())
            or can_approve_knowledge(_role(), is_college_quality_lead=_cq())
        ):
            return jsonify({"status": "error", "message": "لا صلاحية للتصدير"}), 403
        with get_connection() as conn:
            data = export_approved_knowledge_zip(
                conn, department_id=_parse_dept(conn)
            )
        return send_file(
            io.BytesIO(data),
            mimetype="application/zip",
            as_attachment=True,
            download_name="quality_knowledge_approved_export.zip",
        )

    @bp.route("/api/assistant/knowledge/seed", methods=["POST"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean")
    def quality_knowledge_seed_api():
        with get_connection() as conn:
            data = request.get_json(silent=True) or {}
            force = bool(data.get("force"))
            if force:
                refs = seed_approved_global_refs_into_knowledge(
                    conn, actor=_actor(), force=True
                )
                from backend.core.quality_assistant_catalog import (
                    exportable_specialty_packs,
                    specialty_pack_to_markdown,
                )

                payload = exportable_specialty_packs(primary_only=True)
                n = 0
                for pack in payload.get("packs") or []:
                    create_knowledge_doc(
                        conn,
                        title_ar=f"حزمة مراجع — {pack.get('title_ar')} (إعادة بذر)",
                        actor=_actor(),
                        category="global_summary",
                        body_text=specialty_pack_to_markdown(pack),
                        source_label_ar="كتالوج مساعد الجودة",
                        status="approved",
                    )
                    n += 1
                return jsonify(
                    {
                        "status": "ok",
                        "seeded": n + int(refs.get("seeded") or 0),
                        "packs_seeded": n,
                        "refs_seeded": int(refs.get("seeded") or 0),
                    }
                )
            return jsonify(seed_specialty_packs_into_knowledge(conn, actor=_actor()))
