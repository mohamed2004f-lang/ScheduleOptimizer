"""اعتماد مؤسسي — خريطة امتثال (هـ-1)."""

from __future__ import annotations

import datetime
from typing import Any

import os

from flask import jsonify, render_template, request, send_file, session

from backend.core.accreditation_catalog import (
    CATALOG_VERSION,
    COMPLIANCE_STATUS_LABELS,
    DOMAIN_LABELS,
    SOURCE_TYPE_LABELS,
    ensure_accreditation_catalog,
    list_active_catalog_versions,
    resolve_catalog_version,
)
from backend.core.auth import role_required
from backend.services.quality_metrics import term_label_from_conn
from backend.services.utilities import get_connection


def _rows(cur, sql: str, params=()) -> list[dict[str, Any]]:
    cur.execute(sql, params)
    rows = cur.fetchall() or []
    desc = cur.description or ()
    keys = [d[0] for d in desc]
    out = []
    for r in rows:
        if hasattr(r, "keys"):
            try:
                out.append({k: r[k] for k in r.keys()})
                continue
            except Exception:
                pass
        out.append({keys[i]: r[i] for i in range(min(len(keys), len(r)))})
    return out


def _assessment_map(
    cur, semester: str, department_id: int | None
) -> dict[int, dict[str, Any]]:
    dept_clause = "department_id IS NULL" if department_id is None else "department_id = ?"
    params: list[Any] = [semester]
    if department_id is not None:
        params.append(int(department_id))
    rows = _rows(
        cur,
        f"""
        SELECT id, indicator_id, score_percent, compliance_status, notes, updated_at, updated_by
        FROM accreditation_assessments
        WHERE semester = ? AND {dept_clause}
        """,
        tuple(params),
    )
    return {int(r["indicator_id"]): r for r in rows}


def _ensure_accreditation_tables(conn) -> None:
    from backend.database.database import table_exists

    if not table_exists(conn, "accreditation_standards"):
        cur = conn.cursor()
        if hasattr(conn, "executescript"):
            from backend.database.database import TABLES_SCHEMA

            for key in (
                "accreditation_standards",
                "accreditation_indicators",
                "accreditation_assessments",
                "accreditation_evidence",
                "accreditation_manual_inputs",
                "accreditation_improvement_plans",
            ):
                ddl = TABLES_SCHEMA.get(key)
                if ddl:
                    conn.executescript(ddl)
        conn.commit()


def build_compliance_map(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
    ensure_seed: bool = True,
    catalog_version: str | None = None,
) -> dict[str, Any]:
    _ensure_accreditation_tables(conn)
    if ensure_seed:
        ensure_accreditation_catalog(conn)
    cur = conn.cursor()
    cat_ver = resolve_catalog_version(conn, catalog_version)
    sem = (semester or term_label_from_conn(conn)).strip()
    assessments = _assessment_map(cur, sem, department_id)
    from backend.services.accreditation_evidence import evidence_counts_by_indicator

    ev_counts = evidence_counts_by_indicator(conn, sem, department_id)

    standards = _rows(
        cur,
        """
        SELECT id, domain_code, code, title_ar, description, weight_percent, sort_order
        FROM accreditation_standards
        WHERE catalog_version = ? AND COALESCE(is_active, 1) = 1
        ORDER BY domain_code, sort_order, code
        """,
        (cat_ver,),
    )
    indicators = _rows(
        cur,
        """
        SELECT i.id, i.standard_id, i.code, i.title_ar, i.source_type, i.target_hint_ar
        FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE s.catalog_version = ? AND COALESCE(i.is_active, 1) = 1 AND COALESCE(s.is_active, 1) = 1
        ORDER BY i.standard_id, i.sort_order, i.code
        """,
        (cat_ver,),
    )
    by_standard: dict[int, list[dict[str, Any]]] = {}
    for ind in indicators:
        sid = int(ind["standard_id"])
        iid = int(ind["id"])
        asm = assessments.get(iid)
        status = (asm or {}).get("compliance_status") or "not_started"
        by_standard.setdefault(sid, []).append(
            {
                "id": iid,
                "code": ind.get("code"),
                "title_ar": ind.get("title_ar"),
                "source_type": ind.get("source_type"),
                "source_type_label": SOURCE_TYPE_LABELS.get(
                    ind.get("source_type") or "", ind.get("source_type")
                ),
                "target_hint_ar": ind.get("target_hint_ar") or "",
                "is_auto_computable": (ind.get("source_type") or "") in ("auto", "hybrid"),
                "evidence_count": ev_counts.get(iid, 0),
                "assessment": (
                    {
                        "id": asm.get("id"),
                        "score_percent": asm.get("score_percent"),
                        "compliance_status": status,
                        "compliance_status_label": COMPLIANCE_STATUS_LABELS.get(
                            status, status
                        ),
                        "notes": asm.get("notes") or "",
                        "updated_at": asm.get("updated_at"),
                        "updated_by": asm.get("updated_by"),
                    }
                    if asm
                    else {
                        "compliance_status": "not_started",
                        "compliance_status_label": COMPLIANCE_STATUS_LABELS["not_started"],
                        "score_percent": None,
                        "notes": "",
                    }
                ),
            }
        )

    domains_out: list[dict[str, Any]] = []
    summary = {
        "indicators_total": 0,
        "not_started": 0,
        "in_progress": 0,
        "partial": 0,
        "met": 0,
        "gap": 0,
    }
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for st in standards:
        dc = str(st.get("domain_code") or "other")
        by_domain.setdefault(dc, [])
        inds = by_standard.get(int(st["id"]), [])
        counts = {k: 0 for k in ("met", "partial", "in_progress", "gap", "not_started")}
        for ind in inds:
            summary["indicators_total"] += 1
            st_key = ind["assessment"]["compliance_status"]
            if st_key in counts:
                counts[st_key] += 1
            if st_key in summary:
                summary[st_key] += 1
        by_domain[dc].append(
            {
                "id": st["id"],
                "code": st.get("code"),
                "title_ar": st.get("title_ar"),
                "description": st.get("description") or "",
                "weight_percent": st.get("weight_percent"),
                "indicators": inds,
                "counts": counts,
            }
        )

    for dc in sorted(by_domain.keys(), key=lambda x: list(DOMAIN_LABELS.keys()).index(x) if x in DOMAIN_LABELS else 99):
        domains_out.append(
            {
                "code": dc,
                "label": DOMAIN_LABELS.get(dc, dc),
                "standards": by_domain[dc],
            }
        )

    filled = summary["indicators_total"] - summary["not_started"]
    progress_pct = (
        round(100.0 * filled / summary["indicators_total"], 1)
        if summary["indicators_total"]
        else 0.0
    )

    return {
        "status": "ok",
        "catalog_version": cat_ver,
        "semester": sem,
        "department_id": department_id,
        "scope_label_ar": "مؤسسي (كلية)" if department_id is None else f"قسم #{department_id}",
        "domains": domains_out,
        "summary": {**summary, "documented_progress_percent": progress_pct},
    }


def _dept_scope(conn):
    from backend.services.academic_quality import _resolve_department_scope

    return _resolve_department_scope(conn)


def register_institutional_accreditation_routes(bp) -> None:
    """تسجيل مسارات الاعتماد المؤسسي على blueprint الجودة."""

    @bp.route("/accreditation/map", methods=["GET"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_map_page():
        from backend.services.accreditation_evidence import build_checklist_status
        from backend.services.accreditation_manual import (
            MANUAL_SECTIONS,
            PLAN_PRIORITY_LABELS,
            PLAN_STATUS_LABELS,
            get_manual_inputs,
            list_improvement_plans,
        )
        from backend.services.accreditation_metrics import (
            ACCREDITATION_COORDINATOR_ROLES,
            QAA_HIGHER_ED_URL,
        )

        semester = (request.args.get("semester") or "").strip()
        catalog_param = (request.args.get("catalog_version") or "").strip() or None
        checklist: list = []
        manual_bundle: dict = {"sections": MANUAL_SECTIONS, "values": {}}
        improvement_plans: list = []
        catalog_versions: list[str] = [CATALOG_VERSION]
        data: dict = {
            "status": "error",
            "message": "تعذر تحميل الخريطة",
            "catalog_version": CATALOG_VERSION,
            "semester": semester or "",
            "scope_label_ar": "",
            "domains": [],
            "summary": {
                "indicators_total": 0,
                "not_started": 0,
                "in_progress": 0,
                "partial": 0,
                "met": 0,
                "gap": 0,
                "documented_progress_percent": 0,
            },
        }

        try:
            with get_connection() as conn:
                dept_id = _dept_scope(conn)
                if not semester:
                    semester = term_label_from_conn(conn)
                catalog_versions = list_active_catalog_versions(conn)
                data = build_compliance_map(
                    conn,
                    semester=semester,
                    department_id=dept_id,
                    catalog_version=catalog_param,
                )
                checklist = build_checklist_status(conn, semester, dept_id)
                manual_bundle = get_manual_inputs(conn, semester, dept_id)
                improvement_plans = list_improvement_plans(conn, semester, dept_id)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("accreditation_map_page failed")

        return render_template(
            "accreditation_compliance_map.html",
            map_data=data,
            evidence_checklist=checklist,
            manual_bundle=manual_bundle,
            improvement_plans=improvement_plans,
            plan_status_labels=PLAN_STATUS_LABELS,
            plan_priority_labels=PLAN_PRIORITY_LABELS,
            domain_labels=DOMAIN_LABELS,
            status_labels=COMPLIANCE_STATUS_LABELS,
            qaa_url=QAA_HIGHER_ED_URL,
            coordinator_roles=ACCREDITATION_COORDINATOR_ROLES,
            catalog_versions=catalog_versions,
            page_error=None if data.get("status") == "ok" else (data.get("message") or "خطأ في التحميل"),
        )

    @bp.route("/api/accreditation/compliance_map", methods=["GET"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_compliance_map_api():
        semester = (request.args.get("semester") or "").strip() or None
        catalog_param = (request.args.get("catalog_version") or "").strip() or None
        ensure = (request.args.get("ensure") or "1").strip() != "0"
        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            data = build_compliance_map(
                conn,
                semester=semester,
                department_id=dept_id,
                ensure_seed=ensure,
                catalog_version=catalog_param,
            )
        return jsonify(data), 200

    @bp.route("/api/accreditation/catalog_versions", methods=["GET"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_catalog_versions():
        with get_connection() as conn:
            versions = list_active_catalog_versions(conn)
            active = resolve_catalog_version(conn)
        return jsonify({"status": "ok", "versions": versions, "active": active}), 200

    @bp.route("/api/accreditation/meta", methods=["GET"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_meta():
        from backend.services.accreditation_metrics import (
            ACCREDITATION_COORDINATOR_ROLES,
            AUTO_INDICATOR_CODES,
            QAA_HIGHER_ED_URL,
        )

        with get_connection() as conn:
            cat_ver = resolve_catalog_version(conn)
        return jsonify(
            {
                "status": "ok",
                "catalog_version": cat_ver,
                "qaa_higher_ed_url": QAA_HIGHER_ED_URL,
                "qaa_note_ar": (
                    "معايير الاعتماد المؤسسي والبرامجي — التعليم الجامعي "
                    "(الجامعات الحكومية). الوثائق الرسمية على موقع المركز."
                ),
                "auto_indicator_codes": sorted(AUTO_INDICATOR_CODES),
                "coordinator_roles": ACCREDITATION_COORDINATOR_ROLES,
            }
        ), 200

    @bp.route("/api/accreditation/compute_auto", methods=["POST"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_compute_auto():
        from backend.services.accreditation_metrics import apply_auto_assessments

        data = request.get_json(force=True) or {}
        only_ns = data.get("only_not_started", True)
        if isinstance(only_ns, str):
            only_ns = only_ns.strip().lower() not in ("0", "false", "no")
        codes = data.get("indicator_codes")
        if codes is not None and not isinstance(codes, list):
            codes = None
        actor = (session.get("user") or "").strip()
        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (data.get("semester") or "").strip() or term_label_from_conn(conn)
            result = apply_auto_assessments(
                conn,
                semester=sem,
                department_id=dept_id,
                actor=actor or "system:auto",
                only_not_started=bool(only_ns),
                indicator_codes=codes,
            )
        return jsonify(result), 200

    @bp.route("/api/accreditation/compute_auto/preview", methods=["GET"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_compute_auto_preview():
        from backend.services.accreditation_metrics import (
            AUTO_INDICATOR_CODES,
            compute_indicator_auto,
        )

        code = (request.args.get("indicator_code") or "").strip().upper()
        if not code:
            return jsonify({"status": "error", "message": "indicator_code مطلوب"}), 400
        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            if code == "__ALL__":
                previews = []
                for c in sorted(AUTO_INDICATOR_CODES):
                    previews.append(
                        compute_indicator_auto(conn, c, semester=sem, department_id=dept_id)
                    )
                return jsonify({"status": "ok", "items": previews}), 200
            item = compute_indicator_auto(conn, code, semester=sem, department_id=dept_id)
        return jsonify({"status": "ok", **item}), 200

    @bp.route("/api/accreditation/ensure_catalog", methods=["POST"])
    @role_required("admin", "admin_main")
    def accreditation_ensure_catalog():
        with get_connection() as conn:
            stats = ensure_accreditation_catalog(conn)
        return jsonify({"status": "ok", **stats}), 200

    @bp.route("/api/accreditation/assessment/save", methods=["POST"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_assessment_save():
        data = request.get_json(force=True) or {}
        indicator_id = data.get("indicator_id")
        if not indicator_id:
            return jsonify({"status": "error", "message": "indicator_id مطلوب"}), 400
        status = (data.get("compliance_status") or "not_started").strip().lower()
        if status not in COMPLIANCE_STATUS_LABELS:
            return jsonify({"status": "error", "message": "حالة غير صالحة"}), 400
        score = data.get("score_percent")
        notes = (data.get("notes") or "").strip()[:2000]
        actor = (session.get("user") or "").strip()
        now = datetime.datetime.utcnow().isoformat()

        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (data.get("semester") or "").strip() or term_label_from_conn(conn)
            cur = conn.cursor()
            if dept_id is None:
                cur.execute(
                    """
                    DELETE FROM accreditation_assessments
                    WHERE semester = ? AND indicator_id = ? AND department_id IS NULL
                    """,
                    (sem, int(indicator_id)),
                )
                cur.execute(
                    """
                    INSERT INTO accreditation_assessments
                    (semester, department_id, indicator_id, score_percent, compliance_status,
                     notes, updated_at, updated_by)
                    VALUES (?, NULL, ?, ?, ?, ?, ?, ?)
                    """,
                    (sem, int(indicator_id), score, status, notes, now, actor),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO accreditation_assessments
                    (semester, department_id, indicator_id, score_percent, compliance_status,
                     notes, updated_at, updated_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (semester, department_id, indicator_id) DO UPDATE SET
                        score_percent = excluded.score_percent,
                        compliance_status = excluded.compliance_status,
                        notes = excluded.notes,
                        updated_at = excluded.updated_at,
                        updated_by = excluded.updated_by
                    """,
                    (sem, int(dept_id), int(indicator_id), score, status, notes, now, actor),
                )
            conn.commit()
        return jsonify({"status": "ok"}), 200

    @bp.route("/api/accreditation/evidence/checklist", methods=["GET"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_evidence_checklist():
        from backend.services.accreditation_evidence import build_checklist_status

        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            items = build_checklist_status(conn, sem, dept_id)
        return jsonify({"status": "ok", "semester": sem, "items": items}), 200

    @bp.route("/api/accreditation/evidence/list", methods=["GET"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_evidence_list():
        from backend.services.accreditation_evidence import list_evidence

        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            iid = request.args.get("indicator_id")
            ck = (request.args.get("checklist_key") or "").strip() or None
            items = list_evidence(
                conn,
                semester=sem,
                department_id=dept_id,
                indicator_id=int(iid) if iid else None,
                checklist_key=ck,
            )
        return jsonify({"status": "ok", "semester": sem, "items": items}), 200

    @bp.route("/api/accreditation/evidence/upload", methods=["POST"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_evidence_upload():
        from backend.services.accreditation_evidence import save_file_evidence

        f = request.files.get("file")
        if not f:
            return jsonify({"status": "error", "message": "file مطلوب"}), 400
        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (request.form.get("semester") or "").strip() or term_label_from_conn(conn)
            raw = f.read()
            iid = request.form.get("indicator_id")
            sid = request.form.get("standard_id")
            try:
                result = save_file_evidence(
                    conn,
                    semester=sem,
                    department_id=dept_id,
                    raw=raw,
                    original_name=(f.filename or "document").strip(),
                    mime_type=(f.mimetype or "").strip(),
                    uploaded_by=(session.get("user") or "").strip(),
                    indicator_id=int(iid) if iid else None,
                    standard_id=int(sid) if sid else None,
                    checklist_key=(request.form.get("checklist_key") or "").strip() or None,
                    title_ar=(request.form.get("title_ar") or "").strip() or None,
                    description=(request.form.get("description") or "").strip() or None,
                )
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify({"status": "ok", **result}), 200

    @bp.route("/api/accreditation/evidence/link", methods=["POST"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_evidence_link():
        from backend.services.accreditation_evidence import save_link_evidence

        data = request.get_json(force=True) or {}
        url = (data.get("external_url") or "").strip()
        if not url:
            return jsonify({"status": "error", "message": "external_url مطلوب"}), 400
        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (data.get("semester") or "").strip() or term_label_from_conn(conn)
            try:
                result = save_link_evidence(
                    conn,
                    semester=sem,
                    department_id=dept_id,
                    external_url=url,
                    uploaded_by=(session.get("user") or "").strip(),
                    indicator_id=int(data["indicator_id"]) if data.get("indicator_id") else None,
                    standard_id=int(data["standard_id"]) if data.get("standard_id") else None,
                    checklist_key=(data.get("checklist_key") or "").strip() or None,
                    title_ar=(data.get("title_ar") or "").strip() or None,
                    description=(data.get("description") or "").strip() or None,
                )
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify({"status": "ok", **result}), 200

    @bp.route("/api/accreditation/evidence/file/<int:evidence_id>", methods=["GET"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_evidence_download(evidence_id: int):
        from backend.services.accreditation_evidence import get_evidence_file

        with get_connection() as conn:
            meta = get_evidence_file(conn, evidence_id)
        if not meta:
            return jsonify({"status": "error", "message": "الدليل غير موجود"}), 404
        path = meta.get("stored_path") or ""
        if not path or not os.path.isfile(path):
            return jsonify({"status": "error", "message": "الملف غير موجود على القرص"}), 404
        return send_file(
            path,
            as_attachment=True,
            download_name=meta.get("original_name") or "evidence",
            mimetype=meta.get("mime_type") or "application/octet-stream",
        )

    @bp.route("/api/accreditation/evidence/<int:evidence_id>", methods=["DELETE"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_evidence_delete(evidence_id: int):
        from backend.services.accreditation_evidence import soft_delete_evidence

        with get_connection() as conn:
            ok = soft_delete_evidence(conn, evidence_id)
        if not ok:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        return jsonify({"status": "ok"}), 200

    @bp.route("/api/accreditation/manual_inputs", methods=["GET"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_manual_inputs_get():
        from backend.services.accreditation_manual import get_manual_inputs

        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            data = get_manual_inputs(conn, sem, dept_id)
        return jsonify({"status": "ok", **data}), 200

    @bp.route("/api/accreditation/manual_inputs/save", methods=["POST"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_manual_inputs_save():
        from backend.services.accreditation_manual import save_manual_inputs

        data = request.get_json(force=True) or {}
        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (data.get("semester") or "").strip() or term_label_from_conn(conn)
            try:
                result = save_manual_inputs(
                    conn,
                    semester=sem,
                    department_id=dept_id,
                    payload=data,
                    actor=(session.get("user") or "").strip(),
                )
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify({"status": "ok", **result}), 200

    @bp.route("/api/accreditation/improvement_plans", methods=["GET"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_improvement_plans_list():
        from backend.services.accreditation_manual import list_improvement_plans

        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            items = list_improvement_plans(conn, sem, dept_id)
        return jsonify({"status": "ok", "semester": sem, "items": items}), 200

    @bp.route("/api/accreditation/improvement_plans/save", methods=["POST"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_improvement_plans_save():
        from backend.services.accreditation_manual import save_improvement_plan

        data = request.get_json(force=True) or {}
        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (data.get("semester") or "").strip() or term_label_from_conn(conn)
            plan_id = data.get("id")
            try:
                result = save_improvement_plan(
                    conn,
                    semester=sem,
                    department_id=dept_id,
                    plan_id=int(plan_id) if plan_id else None,
                    data=data,
                    actor=(session.get("user") or "").strip(),
                )
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify({"status": "ok", **result}), 200

    @bp.route("/api/accreditation/improvement_plans/<int:plan_id>", methods=["DELETE"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_improvement_plans_delete(plan_id: int):
        from backend.services.accreditation_manual import delete_improvement_plan

        with get_connection() as conn:
            ok = delete_improvement_plan(conn, plan_id)
        if not ok:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        return jsonify({"status": "ok"}), 200

    @bp.route("/api/accreditation/export/xlsx", methods=["GET"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_export_xlsx():
        from backend.core.accreditation_workbook import frames_for_accreditation_workbook
        from backend.services.accreditation_evidence import build_checklist_status
        from backend.services.accreditation_manual import get_manual_inputs, list_improvement_plans
        from backend.services.utilities import excel_response_from_frames

        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            cat_q = (request.args.get("catalog_version") or "").strip() or None
            map_data = build_compliance_map(
                conn, semester=sem, department_id=dept_id, catalog_version=cat_q
            )
            manual = get_manual_inputs(conn, sem, dept_id)
            checklist = build_checklist_status(conn, sem, dept_id)
            plans = list_improvement_plans(conn, sem, dept_id)
        frames = frames_for_accreditation_workbook(
            map_data, manual_bundle=manual, checklist=checklist, plans=plans
        )
        prefix = f"accreditation_workbook_{sem.replace(' ', '_')}"
        return excel_response_from_frames(frames, filename_prefix=prefix)

    @bp.route("/api/accreditation/export/pdf", methods=["GET"])
    @role_required("admin", "admin_main", "head_of_department")
    def accreditation_export_pdf():
        from backend.core.accreditation_workbook import html_for_accreditation_workbook
        from backend.services.accreditation_evidence import build_checklist_status
        from backend.services.accreditation_manual import get_manual_inputs, list_improvement_plans
        from backend.services.utilities import pdf_response_from_html

        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            cat_q = (request.args.get("catalog_version") or "").strip() or None
            map_data = build_compliance_map(
                conn, semester=sem, department_id=dept_id, catalog_version=cat_q
            )
            manual = get_manual_inputs(conn, sem, dept_id)
            checklist = build_checklist_status(conn, sem, dept_id)
            plans = list_improvement_plans(conn, sem, dept_id)
        html = html_for_accreditation_workbook(
            map_data, manual_bundle=manual, checklist=checklist, plans=plans
        )
        return pdf_response_from_html(html, filename_prefix=f"accreditation_{sem.replace(' ', '_')}")

    @bp.route("/api/accreditation/import_catalog/template", methods=["GET"])
    @role_required("admin", "admin_main")
    def accreditation_import_template():
        import pandas as pd

        from backend.services.accreditation_catalog_import import template_rows
        from backend.services.utilities import excel_response_from_df

        df = pd.DataFrame(template_rows())
        return excel_response_from_df(df, filename_prefix="accreditation_catalog_template")

    @bp.route("/api/accreditation/import_catalog", methods=["POST"])
    @role_required("admin", "admin_main")
    def accreditation_import_catalog():
        from backend.services.accreditation_catalog_import import import_catalog_from_excel

        f = request.files.get("file")
        if not f:
            return jsonify({"status": "error", "message": "file مطلوب"}), 400
        deactivate = (request.form.get("deactivate_previous") or "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        with get_connection() as conn:
            try:
                result = import_catalog_from_excel(
                    conn,
                    f.read(),
                    deactivate_previous=deactivate,
                    actor=(session.get("user") or "").strip(),
                )
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify(result), 200
