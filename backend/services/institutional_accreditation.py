"""اعتماد مؤسسي — خريطة امتثال (هـ-1)."""

from __future__ import annotations

import datetime
from typing import Any

import os

from flask import jsonify, render_template, request, send_file, session

from backend.core.accreditation_catalog import (
    ACCREDITATION_MAP_SCOPES,
    CATALOG_VERSION_LABELS,
    COMPLIANCE_STATUS_LABELS,
    DOMAIN_LABELS,
    QAA_AXIS_OPTIONS,
    QAA_INST_CATALOG_VERSION,
    SOURCE_TYPE_LABELS,
    catalog_scope_label,
    ensure_accreditation_catalog,
    list_operational_catalog_versions,
    map_scope_meta,
    resolve_catalog_version,
    resolve_map_catalog_scope,
)
from backend.core.accreditation_program_scope import (
    ensure_accreditation_program_columns,
    has_accreditation_program_id_column,
    list_accreditation_programs,
    resolve_accreditation_org_scope,
)
from backend.core.accreditation_evidence_types import (
    EVIDENCE_CATEGORY_LABELS,
    LINK_MODE_LABELS,
)
from backend.core.auth import (
    accreditation_catalog_editor_required,
    accreditation_evidence_binder_required,
    can_bind_accreditation_evidence,
    can_edit_accreditation_catalog,
    role_required,
)
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
    cur,
    semester: str,
    department_id: int | None,
    *,
    program_id: int | None = None,
    use_program_id: bool = False,
) -> dict[int, dict[str, Any]]:
    params: list[Any] = [semester]
    if use_program_id and program_id is not None:
        clause = "program_id = ?"
        params.append(int(program_id))
    elif use_program_id and program_id is None and department_id is None:
        clause = "program_id IS NULL AND department_id IS NULL"
    elif department_id is None:
        clause = "department_id IS NULL"
    else:
        clause = "department_id = ?"
        params.append(int(department_id))
        if use_program_id and program_id is not None:
            # صفوف قديمة بلا program_id أو المطابقة الجديدة
            clause = "(department_id = ? AND (program_id IS NULL OR program_id = ?))"
            params = [semester, int(department_id), int(program_id)]
    rows = _rows(
        cur,
        f"""
        SELECT id, indicator_id, score_percent, compliance_status, notes, updated_at, updated_by
        FROM accreditation_assessments
        WHERE semester = ? AND {clause}
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
                "accreditation_evidence_types",
                "accreditation_indicator_evidence_rules",
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
    program_id: int | None = None,
    ensure_seed: bool = True,
    catalog_version: str | None = None,
    org_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_accreditation_tables(conn)
    ensure_accreditation_program_columns(conn)
    if ensure_seed:
        ensure_accreditation_catalog(conn)
    cur = conn.cursor()
    cat_ver = resolve_catalog_version(conn, catalog_version)
    sem = (semester or term_label_from_conn(conn)).strip()
    use_pid = has_accreditation_program_id_column(conn)
    assessments = _assessment_map(
        cur,
        sem,
        department_id,
        program_id=program_id,
        use_program_id=use_pid and program_id is not None,
    )
    from backend.services.accreditation_evidence import evidence_counts_by_indicator

    ev_counts = evidence_counts_by_indicator(conn, sem, department_id)
    from backend.services.accreditation_evidence_matrix import (
        build_indicator_evidence_coverage_map,
    )

    coverage_map = build_indicator_evidence_coverage_map(
        conn,
        semester=sem,
        department_id=department_id,
        catalog_version=cat_ver,
        assessments=assessments,
        ev_counts=ev_counts,
    )

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
        SELECT i.id, i.standard_id, i.code, i.title_ar, i.source_type, i.target_hint_ar,
               i.sort_order
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
                "evidence_coverage": coverage_map.get(iid),
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
        numbered_inds: list[dict[str, Any]] = []
        for seq, ind in enumerate(inds, start=1):
            sort_ord = ind.get("sort_order")
            try:
                seq_n = int(sort_ord) if sort_ord else seq
            except (TypeError, ValueError):
                seq_n = seq
            if seq_n <= 0:
                seq_n = seq
            numbered_inds.append({**ind, "seq": seq_n})
        counts = {k: 0 for k in ("met", "partial", "in_progress", "gap", "not_started")}
        for ind in numbered_inds:
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
                "indicators": numbered_inds,
                "indicator_count": len(numbered_inds),
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

    org = org_scope or {}
    scope_label = catalog_scope_label(
        cat_ver,
        department_id,
        program_name_ar=org.get("program_name_ar") or org.get("department_name_ar"),
        org_label_ar=org.get("label_ar"),
    )

    return {
        "status": "ok",
        "catalog_version": cat_ver,
        "semester": sem,
        "department_id": department_id,
        "program_id": program_id if program_id is not None else org.get("program_id"),
        "program_code": org.get("program_code"),
        "program_name_ar": org.get("program_name_ar"),
        "org_level": org.get("org_level"),
        "map_scope_key": org.get("map_scope_key"),
        "scope_label_ar": scope_label,
        "catalog_version_label_ar": CATALOG_VERSION_LABELS.get(cat_ver, cat_ver),
        "domains": domains_out,
        "summary": {**summary, "documented_progress_percent": progress_pct},
    }


def _dept_scope(conn):
    from backend.services.academic_quality import _resolve_department_scope

    return _resolve_department_scope(conn)


def _request_int_arg(name: str) -> int | None:
    raw = (request.args.get(name) or "").strip()
    if not raw or raw.lower() in ("null", "none", "all"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _resolve_map_org_scope(
    conn,
    *,
    scope_key: str,
    payload: dict | None = None,
) -> dict[str, Any]:
    """مؤسسي = كلية؛ برامجي = برنامج الأساس للقسم (مع دعم اختيار صريح)."""
    ensure_accreditation_program_columns(conn)
    scoped_dept = _dept_scope(conn)
    payload = payload or {}
    req_dept = payload.get("department_id")
    req_prog = payload.get("program_id")
    if req_dept is None:
        req_dept = _request_int_arg("department_id")
    if req_prog is None:
        req_prog = _request_int_arg("program_id")
    if isinstance(req_dept, str) and req_dept.strip().isdigit():
        req_dept = int(req_dept)
    if isinstance(req_prog, str) and req_prog.strip().isdigit():
        req_prog = int(req_prog)

    if scoped_dept is not None:
        # رئيس قسم: لا يتجاوز قسمه
        dept_id = int(scoped_dept)
        prog_id = int(req_prog) if req_prog is not None else None
        if prog_id is not None:
            org = resolve_accreditation_org_scope(
                conn, map_scope_key=scope_key, department_id=dept_id, program_id=prog_id
            )
            if org.get("department_id") != dept_id:
                org = resolve_accreditation_org_scope(
                    conn, map_scope_key=scope_key, department_id=dept_id
                )
            return org
        return resolve_accreditation_org_scope(
            conn, map_scope_key=scope_key, department_id=dept_id
        )

    return resolve_accreditation_org_scope(
        conn,
        map_scope_key=scope_key,
        department_id=int(req_dept) if req_dept is not None else None,
        program_id=int(req_prog) if req_prog is not None else None,
    )


def _resolve_binding_department(conn, payload: dict) -> int | None:
    """نطاق القسم لربط الأدلة — يُلزم رئيس القسم بقسمه."""
    scoped = _dept_scope(conn)
    if scoped is not None:
        return int(scoped)
    if can_edit_accreditation_catalog():
        raw = payload.get("department_id")
        if raw in (None, "", "null"):
            return None
        return int(raw)
    return None


def register_institutional_accreditation_routes(bp) -> None:
    """تسجيل مسارات الاعتماد المؤسسي على blueprint الجودة."""

    @bp.route("/accreditation/map", methods=["GET"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
        scope_param = (request.args.get("scope") or "").strip() or None
        catalog_param = (request.args.get("catalog_version") or "").strip() or None
        checklist: list = []
        manual_bundle: dict = {"sections": MANUAL_SECTIONS, "values": {}}
        improvement_plans: list = []
        catalog_versions: list[str] = [QAA_INST_CATALOG_VERSION]
        data: dict = {
            "status": "error",
            "message": "تعذر تحميل الخريطة",
            "catalog_version": QAA_INST_CATALOG_VERSION,
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

        active_scope_key = "inst"
        page_title_ar = "خريطة امتثال — اعتماد مؤسسي"
        programs_available: list = []
        org_scope: dict = {}
        try:
            with get_connection() as conn:
                if not semester:
                    semester = term_label_from_conn(conn)
                catalog_versions = list_operational_catalog_versions(conn)
                resolved_catalog, active_scope_key = resolve_map_catalog_scope(
                    conn,
                    scope=scope_param,
                    catalog_version=catalog_param,
                )
                org_scope = _resolve_map_org_scope(conn, scope_key=active_scope_key)
                data = build_compliance_map(
                    conn,
                    semester=semester,
                    department_id=org_scope.get("department_id"),
                    program_id=org_scope.get("program_id"),
                    catalog_version=resolved_catalog,
                    org_scope=org_scope,
                )
                page_title_ar = map_scope_meta(active_scope_key).get(
                    "page_title_ar", page_title_ar
                )
                dept_for_aux = org_scope.get("department_id")
                checklist = build_checklist_status(conn, semester, dept_for_aux)
                manual_bundle = get_manual_inputs(conn, semester, dept_for_aux)
                improvement_plans = list_improvement_plans(conn, semester, dept_for_aux)
                programs_available = [
                    p for p in list_accreditation_programs(conn) if p.get("scope_ready")
                ]
        except Exception:
            import logging

            logging.getLogger(__name__).exception("accreditation_map_page failed")

        from backend.core.auth import _normalize_role

        user_role = _normalize_role((session.get("user_role") or "").strip())
        show_evidence_matrix_tab = can_edit_accreditation_catalog(user_role)
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
            catalog_version_labels=CATALOG_VERSION_LABELS,
            qaa_axis_options=QAA_AXIS_OPTIONS,
            user_role=user_role,
            is_admin_main=user_role in ("admin", "admin_main"),
            can_edit_accreditation_catalog=can_edit_accreditation_catalog(user_role),
            can_bind_accreditation_sources=can_bind_accreditation_evidence(user_role),
            show_evidence_matrix_tab=show_evidence_matrix_tab,
            link_mode_labels=LINK_MODE_LABELS,
            evidence_category_labels=EVIDENCE_CATEGORY_LABELS,
            map_scopes=ACCREDITATION_MAP_SCOPES,
            active_scope_key=active_scope_key,
            page_title_ar=page_title_ar,
            programs_available=programs_available,
            org_scope=org_scope,
            page_error=None if data.get("status") == "ok" else (data.get("message") or "خطأ في التحميل"),
        )

    @bp.route("/api/accreditation/compliance_map", methods=["GET"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    def accreditation_compliance_map_api():
        semester = (request.args.get("semester") or "").strip() or None
        scope_param = (request.args.get("scope") or "").strip() or None
        catalog_param = (request.args.get("catalog_version") or "").strip() or None
        ensure = (request.args.get("ensure") or "1").strip() != "0"
        with get_connection() as conn:
            resolved_catalog, scope_key = resolve_map_catalog_scope(
                conn,
                scope=scope_param,
                catalog_version=catalog_param,
            )
            org_scope = _resolve_map_org_scope(conn, scope_key=scope_key)
            data = build_compliance_map(
                conn,
                semester=semester,
                department_id=org_scope.get("department_id"),
                program_id=org_scope.get("program_id"),
                ensure_seed=ensure,
                catalog_version=resolved_catalog,
                org_scope=org_scope,
            )
            data["programs_available"] = [
                p for p in list_accreditation_programs(conn) if p.get("scope_ready")
            ]
            data["org_scope"] = org_scope
        return jsonify(data), 200

    @bp.route("/api/accreditation/catalog_versions", methods=["GET"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    def accreditation_catalog_versions():
        with get_connection() as conn:
            versions = list_operational_catalog_versions(conn)
            active = resolve_catalog_version(conn)
        return jsonify(
            {
                "status": "ok",
                "versions": versions,
                "labels": {v: CATALOG_VERSION_LABELS.get(v, v) for v in versions},
                "active": active,
            }
        ), 200

    @bp.route("/api/accreditation/meta", methods=["GET"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
            scope_param = (data.get("scope") or "").strip() or None
            catalog_param = (data.get("catalog_version") or "").strip() or None
            _cat, scope_key = resolve_map_catalog_scope(
                conn, scope=scope_param, catalog_version=catalog_param
            )
            org_scope = _resolve_map_org_scope(
                conn,
                scope_key=scope_key,
                payload={
                    "department_id": data.get("department_id"),
                    "program_id": data.get("program_id"),
                },
            )
            dept_id = org_scope.get("department_id")
            sem = (data.get("semester") or "").strip() or term_label_from_conn(conn)
            result = apply_auto_assessments(
                conn,
                semester=sem,
                department_id=dept_id,
                actor=actor or "system:auto",
                only_not_started=bool(only_ns),
                indicator_codes=codes,
                catalog_version=_cat,
            )
            result["org_scope"] = org_scope
        return jsonify(result), 200

    @bp.route("/api/accreditation/compute_auto/preview", methods=["GET"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean")
    def accreditation_ensure_catalog():
        with get_connection() as conn:
            stats = ensure_accreditation_catalog(conn)
        return jsonify({"status": "ok", **stats}), 200

    @bp.route("/api/accreditation/assessment/save", methods=["POST"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
            ensure_accreditation_program_columns(conn)
            scope_param = (data.get("scope") or "").strip() or None
            catalog_param = (data.get("catalog_version") or "").strip() or None
            _cat, scope_key = resolve_map_catalog_scope(
                conn, scope=scope_param, catalog_version=catalog_param
            )
            org_scope = _resolve_map_org_scope(
                conn,
                scope_key=scope_key,
                payload={
                    "department_id": data.get("department_id"),
                    "program_id": data.get("program_id"),
                },
            )
            dept_id = org_scope.get("department_id")
            prog_id = org_scope.get("program_id")
            use_pid = has_accreditation_program_id_column(conn)
            sem = (data.get("semester") or "").strip() or term_label_from_conn(conn)
            cur = conn.cursor()
            if dept_id is None:
                if use_pid:
                    cur.execute(
                        """
                        DELETE FROM accreditation_assessments
                        WHERE semester = ? AND indicator_id = ?
                          AND department_id IS NULL AND program_id IS NULL
                        """,
                        (sem, int(indicator_id)),
                    )
                    cur.execute(
                        """
                        INSERT INTO accreditation_assessments
                        (semester, department_id, program_id, indicator_id, score_percent,
                         compliance_status, notes, updated_at, updated_by)
                        VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?)
                        """,
                        (sem, int(indicator_id), score, status, notes, now, actor),
                    )
                else:
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
                if use_pid:
                    cur.execute(
                        """
                        INSERT INTO accreditation_assessments
                        (semester, department_id, program_id, indicator_id, score_percent,
                         compliance_status, notes, updated_at, updated_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (semester, department_id, indicator_id) DO UPDATE SET
                            program_id = excluded.program_id,
                            score_percent = excluded.score_percent,
                            compliance_status = excluded.compliance_status,
                            notes = excluded.notes,
                            updated_at = excluded.updated_at,
                            updated_by = excluded.updated_by
                        """,
                        (
                            sem,
                            int(dept_id),
                            int(prog_id) if prog_id is not None else None,
                            int(indicator_id),
                            score,
                            status,
                            notes,
                            now,
                            actor,
                        ),
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
        return jsonify({"status": "ok", "org_scope": org_scope}), 200

    @bp.route("/api/accreditation/evidence/types", methods=["GET"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    def accreditation_evidence_types_api():
        from backend.services.accreditation_evidence_matrix import list_evidence_types

        with get_connection() as conn:
            items = list_evidence_types(conn)
        return jsonify({"status": "ok", "items": items}), 200

    @bp.route("/api/accreditation/evidence/matrix", methods=["GET"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    def accreditation_evidence_matrix_api():
        from backend.services.accreditation_evidence_matrix import build_evidence_matrix

        catalog_param = (request.args.get("catalog_version") or "").strip() or None
        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            data = build_evidence_matrix(
                conn,
                semester=sem,
                department_id=dept_id,
                catalog_version=catalog_param,
            )
        return jsonify(data), 200

    @bp.route("/api/accreditation/evidence/rules", methods=["GET"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    def accreditation_evidence_rules_list():
        from backend.services.accreditation_evidence_matrix import list_evidence_rules

        catalog_param = (request.args.get("catalog_version") or "").strip() or None
        iid = request.args.get("indicator_id")
        with get_connection() as conn:
            items = list_evidence_rules(
                conn,
                catalog_version=catalog_param,
                indicator_id=int(iid) if iid else None,
            )
        return jsonify({"status": "ok", "items": items}), 200

    @bp.route("/api/accreditation/evidence/permissions", methods=["GET"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    def accreditation_evidence_permissions_api():
        from backend.core.auth import can_bind_accreditation_evidence

        return jsonify({
            "status": "ok",
            "can_edit_catalog": can_edit_accreditation_catalog(),
            "can_bind_sources": can_bind_accreditation_evidence(),
        }), 200

    @bp.route("/api/accreditation/evidence/bindable-sources", methods=["GET"])
    @accreditation_evidence_binder_required
    def accreditation_evidence_bindable_sources_api():
        from backend.services.accreditation_evidence_bindings import build_bindable_sources

        iid = request.args.get("indicator_id")
        if not iid:
            return jsonify({"status": "error", "message": "indicator_id مطلوب"}), 400
        catalog_param = (request.args.get("catalog_version") or "").strip() or None
        etid = request.args.get("evidence_type_id")
        with get_connection() as conn:
            dept_id = _resolve_binding_department(conn, dict(request.args))
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            data = build_bindable_sources(
                conn,
                indicator_id=int(iid),
                semester=sem,
                department_id=dept_id,
                catalog_version=catalog_param,
                evidence_type_id=int(etid) if etid else None,
            )
        return jsonify(data), 200

    @bp.route("/api/accreditation/evidence/bindings", methods=["GET"])
    @accreditation_evidence_binder_required
    def accreditation_evidence_bindings_list_api():
        from backend.services.accreditation_evidence_bindings import list_bindings

        with get_connection() as conn:
            dept_id = _resolve_binding_department(conn, dict(request.args))
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            iid = request.args.get("indicator_id")
            etid = request.args.get("evidence_type_id")
            items = list_bindings(
                conn,
                semester=sem,
                department_id=dept_id,
                indicator_id=int(iid) if iid else None,
                evidence_type_id=int(etid) if etid else None,
            )
        return jsonify({"status": "ok", "semester": sem, "items": items}), 200

    @bp.route("/api/accreditation/evidence/bindings", methods=["POST"])
    @accreditation_evidence_binder_required
    def accreditation_evidence_bindings_save_api():
        from backend.services.accreditation_evidence_bindings import save_binding

        data = request.get_json(force=True) or {}
        try:
            with get_connection() as conn:
                data["department_id"] = _resolve_binding_department(conn, data)
                result = save_binding(
                    conn, data, actor=(session.get("user") or "").strip()
                )
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify(result), 200

    @bp.route("/api/accreditation/evidence/bindings/<int:binding_id>", methods=["DELETE"])
    @accreditation_evidence_binder_required
    def accreditation_evidence_bindings_delete_api(binding_id: int):
        from backend.services.accreditation_evidence_bindings import deactivate_binding

        with get_connection() as conn:
            ok = deactivate_binding(conn, binding_id)
        if not ok:
            return jsonify({"status": "error", "message": "لم يُعثر على الربط"}), 404
        return jsonify({"status": "ok"}), 200

    @bp.route("/api/accreditation/evidence/indicators", methods=["GET"])
    @accreditation_catalog_editor_required
    def accreditation_evidence_indicators_api():
        from backend.services.accreditation_evidence_matrix import list_catalog_indicators

        catalog_param = (request.args.get("catalog_version") or "").strip() or None
        with get_connection() as conn:
            items = list_catalog_indicators(conn, catalog_param)
        return jsonify({"status": "ok", "items": items}), 200

    @bp.route("/api/accreditation/evidence/types", methods=["POST"])
    @accreditation_catalog_editor_required
    def accreditation_evidence_types_save():
        from backend.services.accreditation_evidence_matrix import save_evidence_type

        data = request.get_json(force=True) or {}
        try:
            with get_connection() as conn:
                result = save_evidence_type(
                    conn, data, actor=(session.get("user") or "").strip()
                )
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify(result), 200

    @bp.route("/api/accreditation/evidence/types/<int:type_id>", methods=["DELETE"])
    @accreditation_catalog_editor_required
    def accreditation_evidence_types_delete(type_id: int):
        from backend.services.accreditation_evidence_matrix import deactivate_evidence_type

        try:
            with get_connection() as conn:
                ok = deactivate_evidence_type(conn, type_id)
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        if not ok:
            return jsonify({"status": "error", "message": "لم يُعثر على نوع الدليل"}), 404
        return jsonify({"status": "ok"}), 200

    @bp.route("/api/accreditation/evidence/rules", methods=["POST"])
    @accreditation_catalog_editor_required
    def accreditation_evidence_rules_save():
        from backend.services.accreditation_evidence_matrix import save_evidence_rule

        data = request.get_json(force=True) or {}
        try:
            with get_connection() as conn:
                result = save_evidence_rule(
                    conn, data, actor=(session.get("user") or "").strip()
                )
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify(result), 200

    @bp.route("/api/accreditation/evidence/rules/<int:rule_id>", methods=["DELETE"])
    @accreditation_catalog_editor_required
    def accreditation_evidence_rules_delete(rule_id: int):
        from backend.services.accreditation_evidence_matrix import deactivate_evidence_rule

        with get_connection() as conn:
            ok = deactivate_evidence_rule(conn, rule_id)
        if not ok:
            return jsonify({"status": "error", "message": "لم يُعثر على القاعدة"}), 404
        return jsonify({"status": "ok"}), 200

    @bp.route("/api/accreditation/evidence/checklist", methods=["GET"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    def accreditation_evidence_checklist():
        from backend.services.accreditation_evidence import build_checklist_status

        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            items = build_checklist_status(conn, sem, dept_id)
        return jsonify({"status": "ok", "semester": sem, "items": items}), 200

    @bp.route("/api/accreditation/evidence/list", methods=["GET"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    def accreditation_evidence_delete(evidence_id: int):
        from backend.services.accreditation_evidence import soft_delete_evidence

        with get_connection() as conn:
            ok = soft_delete_evidence(conn, evidence_id)
        if not ok:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        return jsonify({"status": "ok"}), 200

    @bp.route("/api/accreditation/manual_inputs", methods=["GET"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    def accreditation_manual_inputs_get():
        from backend.services.accreditation_manual import get_manual_inputs

        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            data = get_manual_inputs(conn, sem, dept_id)
        return jsonify({"status": "ok", **data}), 200

    @bp.route("/api/accreditation/manual_inputs/save", methods=["POST"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    def accreditation_improvement_plans_list():
        from backend.services.accreditation_manual import list_improvement_plans

        with get_connection() as conn:
            dept_id = _dept_scope(conn)
            sem = (request.args.get("semester") or "").strip() or term_label_from_conn(conn)
            items = list_improvement_plans(conn, sem, dept_id)
        return jsonify({"status": "ok", "semester": sem, "items": items}), 200

    @bp.route("/api/accreditation/improvement_plans/save", methods=["POST"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
    def accreditation_improvement_plans_delete(plan_id: int):
        from backend.services.accreditation_manual import delete_improvement_plan

        with get_connection() as conn:
            ok = delete_improvement_plan(conn, plan_id)
        if not ok:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        return jsonify({"status": "ok"}), 200

    @bp.route("/api/accreditation/export/xlsx", methods=["GET"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
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
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean")
    def accreditation_import_template():
        import pandas as pd

        from backend.services.accreditation_catalog_import import template_rows
        from backend.services.utilities import excel_response_from_df

        df = pd.DataFrame(template_rows())
        return excel_response_from_df(df, filename_prefix="accreditation_catalog_template")

    @bp.route("/api/accreditation/import_catalog", methods=["POST"])
    @role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean")
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
