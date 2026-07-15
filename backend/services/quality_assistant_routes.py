"""مسارات المساعد الذكي لضمان الجودة — أدوار متعددة + تصعيد."""

from __future__ import annotations

from typing import Any

import io

from flask import jsonify, render_template, request, send_file, session

from backend.core.auth import _normalize_role, role_required
from backend.core.quality_assistant_catalog import exportable_specialty_packs
from backend.services.quality_assistant import (
    assistant_bootstrap_payload,
    build_context,
    build_references_zip_bytes,
    build_welcome_brief,
    ensure_quality_assistant_tables,
    list_escalations,
    mark_escalation_status,
    normalize_chat_history,
    resolve_assistant_mode,
    run_quality_assistant,
    save_assistant_feedback,
)
from backend.services.quality_assistant_advanced import (
    build_committee_summary,
    build_style_training_export,
    committee_summary_docx_bytes,
    committee_summary_pdf_bytes,
    llm_config,
    log_usage_event,
    usage_analytics_summary,
)
from backend.services.quality_metrics import term_label_from_conn
from backend.services.utilities import get_connection

_STAFF_ROLES = (
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


def _flags() -> tuple[bool, bool]:
    cq = int(session.get("is_college_quality_lead") or 0) == 1
    dq = int(session.get("is_dept_quality_coordinator") or 0) == 1
    return cq, dq


def _dept_scope(conn) -> int | None:
    from backend.services.academic_quality import _resolve_department_scope

    return _resolve_department_scope(conn)


def _parse_dept_id(conn, raw: Any = None) -> int | None:
    scoped = _dept_scope(conn)
    if scoped is not None:
        return int(scoped)
    if raw in (None, "", "null"):
        raw = request.args.get("department_id")
        if raw in (None, "", "null") and request.is_json:
            body = request.get_json(silent=True) or {}
            raw = body.get("department_id")
    if raw in (None, "", "null"):
        return None
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


def register_quality_assistant_routes(bp) -> None:
    @bp.route("/assistant", methods=["GET"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_page():
        cq, dq = _flags()
        role = _role()
        mode_q = (request.args.get("mode") or "").strip() or None
        with get_connection() as conn:
            ensure_quality_assistant_tables(conn)
            semester = (request.args.get("semester") or term_label_from_conn(conn)).strip()
            dept_id = _parse_dept_id(conn)
            departments = _departments(conn)
            if dept_id is None and departments and role in (
                "admin_main",
                "system_admin",
                "college_dean",
                "academic_vice_dean",
                "admin",
            ):
                dept_id = departments[0]["id"]
            elif dept_id is None and departments and role in ("head_of_department", "instructor"):
                scoped = _dept_scope(conn)
                dept_id = int(scoped) if scoped is not None else departments[0]["id"]
            boot = assistant_bootstrap_payload(
                role=role,
                is_college_quality_lead=cq,
                is_dept_quality_coordinator=dq,
                active_mode=mode_q,
            )
            mode = boot["active_mode"]
            try:
                ctx = build_context(conn, mode=mode, semester=semester, department_id=dept_id)
            except Exception:
                ctx = {"semester": semester, "department": {}, "suggestion_only": True}
            try:
                boot["welcome"] = build_welcome_brief(
                    conn, mode=mode, semester=semester, department_id=dept_id
                )
            except Exception:
                boot["welcome"] = {
                    "greeting_ar": "مرحباً بك في المساعد الذكي.",
                    "tasks": [],
                }
        return render_template(
            "quality_assistant.html",
            bootstrap=boot,
            context=ctx,
            departments=departments,
            selected_department_id=dept_id,
            semester=semester,
            user_role=role,
            page_error=None,
        )

    @bp.route("/assistant/references.json", methods=["GET"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_references_json():
        primary = (request.args.get("all") or "").strip() not in ("1", "true", "yes")
        payload = exportable_specialty_packs(primary_only=primary)
        return jsonify(payload)

    @bp.route("/assistant/references.zip", methods=["GET"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_references_zip():
        primary = (request.args.get("all") or "").strip() not in ("1", "true", "yes")
        data = build_references_zip_bytes(primary_only=primary)
        return send_file(
            io.BytesIO(data),
            mimetype="application/zip",
            as_attachment=True,
            download_name="quality_global_references_packs.zip",
        )

    @bp.route("/api/assistant/bootstrap", methods=["GET"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_bootstrap_api():
        cq, dq = _flags()
        mode_q = (request.args.get("mode") or "").strip() or None
        return jsonify(
            assistant_bootstrap_payload(
                role=_role(),
                is_college_quality_lead=cq,
                is_dept_quality_coordinator=dq,
                active_mode=mode_q,
            )
        )

    @bp.route("/api/assistant/context", methods=["GET"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_context_api():
        cq, dq = _flags()
        mode = resolve_assistant_mode(
            role=_role(),
            requested=(request.args.get("mode") or "").strip() or None,
            is_college_quality_lead=cq,
            is_dept_quality_coordinator=dq,
        )
        with get_connection() as conn:
            semester = (request.args.get("semester") or term_label_from_conn(conn)).strip()
            dept_id = _parse_dept_id(conn)
            ctx = build_context(conn, mode=mode, semester=semester, department_id=dept_id)
        return jsonify({"status": "ok", "mode": mode, "context": ctx})

    @bp.route("/api/assistant/run", methods=["POST"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_run_api():
        data = request.get_json(force=True) or {}
        cq, dq = _flags()
        mode = resolve_assistant_mode(
            role=_role(),
            requested=(data.get("mode") or "").strip() or None,
            is_college_quality_lead=cq,
            is_dept_quality_coordinator=dq,
        )
        intent = (data.get("intent") or "help").strip()
        topic = (data.get("topic") or "").strip()
        notes = (data.get("notes") or data.get("message") or "").strip()
        history = normalize_chat_history(data.get("history"))
        if not history:
            history = normalize_chat_history(session.get("qa_chat_history"))
        try:
            with get_connection() as conn:
                semester = (data.get("semester") or term_label_from_conn(conn)).strip()
                dept_id = _parse_dept_id(conn, data.get("department_id"))
                result = run_quality_assistant(
                    conn,
                    mode=mode,
                    intent=intent,
                    semester=semester,
                    department_id=dept_id,
                    topic=topic,
                    notes=notes,
                    actor=_actor(),
                    history=history,
                )
                try:
                    log_usage_event(
                        conn,
                        mode=mode,
                        intent=intent,
                        channel=(data.get("channel") or "assistant"),
                        page_path=(data.get("page_path") or "")[:260],
                        department_id=dept_id,
                        actor=_actor(),
                    )
                except Exception:
                    pass
            # حدّث ذاكرة الجلسة القصيرة
            updated = list(history)
            if notes:
                updated.append({"role": "user", "text": notes[:2000]})
            reply_text = (result.get("message_ar") or "")[:500]
            if result.get("bullets"):
                reply_text = (reply_text + "\n" + "\n".join(str(b) for b in result["bullets"][:8]))[
                    :2000
                ]
            if reply_text:
                updated.append({"role": "assistant", "text": reply_text})
            session["qa_chat_history"] = normalize_chat_history(updated)
            if result.get("committee_summary"):
                session["qa_committee_summary"] = result["committee_summary"]
            return jsonify(result)
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e), "suggestion_only": True}), 400
        except Exception as e:
            return jsonify({"status": "error", "message": str(e), "suggestion_only": True}), 500

    @bp.route("/api/assistant/feedback", methods=["POST"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_feedback_api():
        data = request.get_json(force=True) or {}
        try:
            with get_connection() as conn:
                dept_id = _parse_dept_id(conn, data.get("department_id"))
                result = save_assistant_feedback(
                    conn,
                    reply_id=(data.get("reply_id") or "").strip(),
                    rating=(data.get("rating") or "").strip(),
                    reason_ar=(data.get("reason_ar") or data.get("reason") or "").strip(),
                    mode=(data.get("mode") or "").strip(),
                    intent=(data.get("intent") or "").strip(),
                    semester=(data.get("semester") or "").strip(),
                    department_id=dept_id,
                    actor=_actor(),
                )
            return jsonify(result)
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/assistant/welcome", methods=["GET"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_welcome_api():
        cq, dq = _flags()
        mode = resolve_assistant_mode(
            role=_role(),
            requested=(request.args.get("mode") or "").strip() or None,
            is_college_quality_lead=cq,
            is_dept_quality_coordinator=dq,
        )
        with get_connection() as conn:
            semester = (request.args.get("semester") or term_label_from_conn(conn)).strip()
            dept_id = _parse_dept_id(conn)
            return jsonify(
                build_welcome_brief(
                    conn, mode=mode, semester=semester, department_id=dept_id
                )
            )

    @bp.route("/api/assistant/escalations", methods=["GET"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_escalations_api():
        cq, dq = _flags()
        mode = resolve_assistant_mode(
            role=_role(),
            requested=(request.args.get("mode") or "").strip() or None,
            is_college_quality_lead=cq,
            is_dept_quality_coordinator=dq,
        )
        # كل وضع يرى التصعيدات الموجّهة إليه (+ الكل للإدارة)
        to_mode = (request.args.get("to_mode") or "").strip() or None
        if not to_mode and mode in (
            "head_of_department",
            "academic_vice_dean",
            "quality_committee",
            "college_dean",
        ):
            to_mode = mode
        with get_connection() as conn:
            dept_id = _parse_dept_id(conn)
            items = list_escalations(conn, to_mode=to_mode, department_id=dept_id)
        return jsonify({"status": "ok", "items": items, "filter_to_mode": to_mode})

    @bp.route("/api/assistant/escalations/<int:escalation_id>/status", methods=["POST"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_escalation_status_api(escalation_id: int):
        data = request.get_json(force=True) or {}
        try:
            with get_connection() as conn:
                result = mark_escalation_status(
                    conn,
                    escalation_id,
                    (data.get("status") or "").strip(),
                    actor=_actor(),
                )
            return jsonify(result)
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    def _committee_summary_from_session_or_build():
        cached = session.get("qa_committee_summary")
        if isinstance(cached, dict) and cached.get("markdown"):
            return cached
        cq, dq = _flags()
        mode = resolve_assistant_mode(
            role=_role(),
            requested=(request.args.get("mode") or "").strip() or None,
            is_college_quality_lead=cq,
            is_dept_quality_coordinator=dq,
        )
        with get_connection() as conn:
            semester = (request.args.get("semester") or term_label_from_conn(conn)).strip()
            dept_id = _parse_dept_id(conn)
            summary = build_committee_summary(
                conn,
                mode=mode,
                semester=semester,
                department_id=dept_id,
                notes="",
                history=normalize_chat_history(session.get("qa_chat_history")),
            )
        session["qa_committee_summary"] = summary
        return summary

    @bp.route("/assistant/export/committee.md", methods=["GET"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_export_committee_md():
        summary = _committee_summary_from_session_or_build()
        data = (summary.get("markdown") or "").encode("utf-8")
        return send_file(
            io.BytesIO(data),
            mimetype="text/markdown; charset=utf-8",
            as_attachment=True,
            download_name="committee_summary_draft.md",
        )

    @bp.route("/assistant/export/committee.docx", methods=["GET"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_export_committee_docx():
        summary = _committee_summary_from_session_or_build()
        try:
            data = committee_summary_docx_bytes(summary)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        return send_file(
            io.BytesIO(data),
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            as_attachment=True,
            download_name="committee_summary_draft.docx",
        )

    @bp.route("/assistant/export/committee.pdf", methods=["GET"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_export_committee_pdf():
        summary = _committee_summary_from_session_or_build()
        data = committee_summary_pdf_bytes(summary)
        if not data:
            # سقوط إلى Markdown إن تعذّر PDF
            md = (summary.get("markdown") or "").encode("utf-8")
            return send_file(
                io.BytesIO(md),
                mimetype="text/markdown; charset=utf-8",
                as_attachment=True,
                download_name="committee_summary_draft.md",
            )
        return send_file(
            io.BytesIO(data),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="committee_summary_draft.pdf",
        )

    @bp.route("/assistant/export/style-pack.zip", methods=["GET"])
    @role_required(
        "admin",
        "admin_main",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
        "head_of_department",
    )
    def quality_assistant_export_style_pack():
        with get_connection() as conn:
            data = build_style_training_export(conn)
        return send_file(
            io.BytesIO(data),
            mimetype="application/zip",
            as_attachment=True,
            download_name="quality_style_training_pack.zip",
        )

    @bp.route("/api/assistant/usage", methods=["GET"])
    @role_required(
        "admin",
        "admin_main",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
        "head_of_department",
    )
    def quality_assistant_usage_api():
        with get_connection() as conn:
            return jsonify(usage_analytics_summary(conn, limit=30))

    @bp.route("/api/assistant/llm_status", methods=["GET"])
    @role_required(*_STAFF_ROLES)
    def quality_assistant_llm_status_api():
        cfg = llm_config()
        return jsonify(
            {
                "status": "ok",
                "enabled": bool(cfg.get("enabled")),
                "configured": bool(cfg.get("base_url") and cfg.get("api_key")),
                "model": cfg.get("model") if cfg.get("enabled") else None,
                "note_ar": (
                    "فعّل QUALITY_ASSISTANT_LLM_ENABLED مع BASE_URL و API_KEY لموصل خارجي اختياري."
                    if not cfg.get("enabled")
                    else "موصل LLM مفعّل — الردود تبقى اقتراحاً فقط."
                ),
                "suggestion_only": True,
            }
        )
