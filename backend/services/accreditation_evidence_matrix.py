"""مصفوفة أدلة الاعتماد — المتوقع مقابل الموجود (المرحلة أ)."""

from __future__ import annotations

import datetime
import json
from typing import Any

from backend.core.accreditation_catalog import (
    DOMAIN_LABELS,
    SOURCE_TYPE_LABELS,
    resolve_catalog_version,
)
from backend.core.accreditation_evidence_types import (
    EVIDENCE_CATEGORY_LABELS,
    FULFILLMENT_STATUS_LABELS,
    LINK_MODE_LABELS,
)
from backend.core.accreditation_evidence_rules_seed import (
    ensure_evidence_rules_for_catalog,
    ensure_evidence_types,
)
from backend.database.database import is_postgresql, table_exists
from backend.services.accreditation_evidence import evidence_counts_by_indicator, list_evidence


_PG_EVIDENCE_BINDING_DDL = {
    "accreditation_evidence_types": """
        CREATE TABLE IF NOT EXISTS accreditation_evidence_types (
            id BIGSERIAL PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            title_ar TEXT NOT NULL,
            description_ar TEXT DEFAULT '',
            category TEXT NOT NULL DEFAULT 'file',
            source_module TEXT DEFAULT '',
            source_ref TEXT DEFAULT '',
            is_system INTEGER NOT NULL DEFAULT 0,
            is_editable INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """,
    "accreditation_indicator_evidence_rules": """
        CREATE TABLE IF NOT EXISTS accreditation_indicator_evidence_rules (
            id BIGSERIAL PRIMARY KEY,
            catalog_version TEXT NOT NULL,
            indicator_id BIGINT NOT NULL,
            evidence_type_id BIGINT NOT NULL,
            link_mode TEXT NOT NULL DEFAULT 'evidence',
            is_required INTEGER NOT NULL DEFAULT 1,
            weight_percent REAL DEFAULT 0,
            config_json TEXT DEFAULT '',
            notes_ar TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            UNIQUE (catalog_version, indicator_id, evidence_type_id),
            CONSTRAINT accred_ev_rule_ind_fk FOREIGN KEY (indicator_id)
                REFERENCES accreditation_indicators(id) ON DELETE CASCADE,
            CONSTRAINT accred_ev_rule_type_fk FOREIGN KEY (evidence_type_id)
                REFERENCES accreditation_evidence_types(id) ON DELETE CASCADE
        )
    """,
}


def ensure_evidence_binding_schema(conn) -> None:
    if not table_exists(conn, "accreditation_evidence_types") or not table_exists(
        conn, "accreditation_indicator_evidence_rules"
    ):
        from backend.database.database import TABLES_SCHEMA

        cur = conn.cursor()
        ddl_map = _PG_EVIDENCE_BINDING_DDL if is_postgresql() else TABLES_SCHEMA
        for key in ("accreditation_evidence_types", "accreditation_indicator_evidence_rules"):
            ddl = ddl_map.get(key)
            if not ddl:
                continue
            if hasattr(conn, "executescript"):
                conn.executescript(ddl)
            else:
                cur.execute(ddl)
        conn.commit()
    ensure_evidence_types(conn)


def _row_dict(row, keys: list[str] | None = None) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    if keys:
        return {keys[i]: row[i] for i in range(min(len(keys), len(row)))}
    return {}


def list_evidence_types(conn) -> list[dict[str, Any]]:
    ensure_evidence_binding_schema(conn)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, code, title_ar, description_ar, category, source_module, source_ref,
               is_system, is_editable, sort_order
        FROM accreditation_evidence_types
        WHERE COALESCE(is_active, 1) = 1
        ORDER BY sort_order, code
        """
    )
    rows = cur.fetchall() or []
    keys = [d[0] for d in (cur.description or ())]
    out = []
    for r in rows:
        d = _row_dict(r, keys)
        d["category_label"] = EVIDENCE_CATEGORY_LABELS.get(d.get("category"), d.get("category"))
        out.append(d)
    return out


def list_evidence_rules(
    conn,
    *,
    catalog_version: str | None = None,
    indicator_id: int | None = None,
) -> list[dict[str, Any]]:
    ensure_evidence_binding_schema(conn)
    cat_ver = resolve_catalog_version(conn, catalog_version)
    ensure_evidence_rules_for_catalog(conn, cat_ver)
    cur = conn.cursor()
    extra = ""
    params: list[Any] = [cat_ver]
    if indicator_id is not None:
        extra += " AND r.indicator_id = ?"
        params.append(int(indicator_id))
    cur.execute(
        f"""
        SELECT r.id, r.catalog_version, r.indicator_id, r.evidence_type_id, r.link_mode,
               r.is_required, r.weight_percent, r.config_json, r.notes_ar, r.sort_order,
               i.code AS indicator_code, i.title_ar AS indicator_title_ar,
               s.code AS standard_code, s.title_ar AS standard_title_ar, s.domain_code,
               t.code AS evidence_type_code, t.title_ar AS evidence_type_title_ar,
               t.category AS evidence_category, t.source_module, t.source_ref
        FROM accreditation_indicator_evidence_rules r
        INNER JOIN accreditation_indicators i ON i.id = r.indicator_id
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        INNER JOIN accreditation_evidence_types t ON t.id = r.evidence_type_id
        WHERE r.catalog_version = ? AND COALESCE(r.is_active, 1) = 1
          AND COALESCE(i.is_active, 1) = 1 AND COALESCE(s.is_active, 1) = 1
          AND COALESCE(t.is_active, 1) = 1 {extra}
        ORDER BY s.domain_code, s.sort_order, i.sort_order, r.sort_order, r.id
        """,
        tuple(params),
    )
    rows = cur.fetchall() or []
    keys = [d[0] for d in (cur.description or ())]
    out = []
    for r in rows:
        d = _row_dict(r, keys)
        d["link_mode_label"] = LINK_MODE_LABELS.get(d.get("link_mode"), d.get("link_mode"))
        d["domain_label"] = DOMAIN_LABELS.get(d.get("domain_code"), d.get("domain_code"))
        d["evidence_category_label"] = EVIDENCE_CATEGORY_LABELS.get(
            d.get("evidence_category"), d.get("evidence_category")
        )
        try:
            d["config"] = json.loads(d.get("config_json") or "{}")
        except json.JSONDecodeError:
            d["config"] = {}
        out.append(d)
    return out


def _survey_has_data(
    conn,
    template_code: str,
    semester: str,
    department_id: int | None,
    *,
    aggregate_cache: dict[str, dict[str, Any]] | None = None,
) -> bool:
    if not template_code:
        return False
    code = template_code.strip()
    if aggregate_cache is not None and code in aggregate_cache:
        agg = aggregate_cache[code]
    else:
        try:
            from backend.services.survey_accreditation import survey_template_aggregate

            agg = survey_template_aggregate(
                conn, code, semester=semester, department_id=department_id
            )
            if aggregate_cache is not None:
                aggregate_cache[code] = agg
        except Exception:
            return False
    if agg.get("aggregated"):
        return True
    if agg.get("response_count", 0) > 0:
        return True
    if agg.get("overall_score_percent") is not None:
        return True
    return False


def _build_survey_aggregate_cache(
    conn,
    *,
    semester: str,
    department_id: int | None,
    template_codes: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    from backend.services.survey_accreditation import survey_template_aggregate

    codes = template_codes or set()
    if not codes:
        from backend.core.qaa_survey_accreditation_map import all_qaa_survey_template_codes

        codes = set(all_qaa_survey_template_codes())
    cache: dict[str, dict[str, Any]] = {}
    for code in codes:
        if not code:
            continue
        try:
            cache[code] = survey_template_aggregate(
                conn, code, semester=semester, department_id=department_id
            )
        except Exception:
            cache[code] = {}
    return cache


def _parse_binding_ref(source_ref: str) -> tuple[str, str]:
    ref = (source_ref or "").strip()
    if ":" in ref:
        kind, payload = ref.split(":", 1)
        return kind.strip().lower(), payload.strip()
    return "", ref


def _binding_fulfillment_status(
    conn,
    binding: dict[str, Any],
    *,
    semester: str,
    department_id: int | None,
    assessment: dict[str, Any] | None,
    aggregate_cache: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """حالة تحقق مصدر مربوط: met | partial | missing + تفاصيل."""
    kind = (binding.get("binding_kind") or "").strip().lower()
    ref = binding.get("source_ref") or ""
    label = (binding.get("label_ar") or ref).strip()
    _, payload = _parse_binding_ref(ref)

    has_score = assessment and assessment.get("score_percent") is not None
    has_notes = bool((assessment or {}).get("notes", "").strip())
    status = (assessment or {}).get("compliance_status") or "not_started"

    if kind == "survey":
        code = payload or ref.replace("survey:", "", 1)
        if code and _survey_has_data(
            conn, code, semester, department_id, aggregate_cache=aggregate_cache
        ):
            return "met", f"مربوط: {label}"
        return "partial", f"مربوط باستبيان — بانتظار بيانات ({label})"

    if kind == "witness":
        eid = payload if payload.isdigit() else ref.rsplit(":", 1)[-1]
        if eid.isdigit():
            witnesses = list_evidence(
                conn,
                semester=semester,
                department_id=department_id,
                indicator_id=int(binding.get("indicator_id") or 0),
            )
            if any(int(w["id"]) == int(eid) for w in witnesses):
                return "met", f"مربوط: {label}"
        return "missing", f"الشاهد المربوط غير متوفر ({label})"

    if kind == "report":
        key = payload or ref.replace("report:", "", 1)
        if key == "course_closure" and table_exists(conn, "course_closure_reports"):
            cur = conn.cursor()
            dept_clause = "1=1"
            params: list[Any] = [semester]
            if department_id is not None:
                dept_clause = "c.department_id = ?"
                params.append(int(department_id))
            try:
                row = cur.execute(
                    f"SELECT COUNT(*) FROM course_closure_reports c WHERE c.semester = ? AND {dept_clause}",
                    tuple(params),
                ).fetchone()
                if int(row[0] if row else 0) > 0:
                    return "met", f"مربوط: {label}"
            except Exception:
                pass
        elif key in ("college_identity", "department_policies", "accreditation_manual"):
            return "partial", f"مربوط: {label} — تحقق يدوي من التقرير"
        return "partial", f"مربوط: {label}"

    if kind == "manual":
        if has_score or has_notes or status in ("met", "partial"):
            return "met", f"مربوط: {label}"
        return "partial", f"مربوط يدوياً — أكمل التقييم"

    return "partial", f"مربوط: {label}"


def _evaluate_rule_fulfillment(
    conn,
    *,
    rule: dict[str, Any],
    semester: str,
    department_id: int | None,
    ev_count: int,
    assessment: dict[str, Any] | None,
    binding: dict[str, Any] | None = None,
    aggregate_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if binding:
        b_status, b_detail = _binding_fulfillment_status(
            conn,
            {**binding, "indicator_id": rule.get("indicator_id")},
            semester=semester,
            department_id=department_id,
            assessment=assessment,
            aggregate_cache=aggregate_cache,
        )
        fulfillment = b_status if b_status in ("met", "partial", "missing") else "partial"
        if fulfillment == "missing":
            fulfillment = "partial"
        if not rule.get("is_required") and fulfillment == "missing":
            fulfillment = "not_applicable"
            b_detail = "دليل داعم اختياري."
        return {
            "status": fulfillment,
            "status_label": FULFILLMENT_STATUS_LABELS.get(fulfillment, fulfillment),
            "detail_ar": b_detail,
            "evidence_count": ev_count,
            "has_survey_data": False,
            "is_bound": True,
            "binding_id": binding.get("id"),
        }

    link_mode = (rule.get("link_mode") or "evidence").strip().lower()
    config = rule.get("config") or {}
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            config = {}

    has_files = ev_count > 0
    has_score = assessment and assessment.get("score_percent") is not None
    status = assessment.get("compliance_status") if assessment else "not_started"
    met_assessment = status in ("met", "partial") and has_score

    survey_tpl = config.get("survey_template") or ""
    src_module = rule.get("source_module") or ""
    src_ref = rule.get("source_ref") or ""
    if not survey_tpl and src_module == "multi_surveys":
        survey_tpl = src_ref

    has_survey = (
        _survey_has_data(
            conn, survey_tpl, semester, department_id, aggregate_cache=aggregate_cache
        )
        if survey_tpl
        else False
    )

    fulfillment = "missing"
    detail_ar = "بانتظار الشاهد أو الربط."

    if link_mode == "auto":
        if met_assessment or has_survey:
            fulfillment = "met"
            detail_ar = "متحقق آلياً من النظام أو التقييم."
        elif has_files:
            fulfillment = "partial"
            detail_ar = "يوجد مرفق داعم؛ التقييم الآلي غير مكتمل."
    elif link_mode == "hybrid":
        if (has_score or has_survey) and has_files:
            fulfillment = "met"
            detail_ar = "تقييم/استبيان + شاهد مرفق."
        elif has_score or has_survey or has_files:
            fulfillment = "partial"
            detail_ar = "جزء من مصادر الهجين متوفر."
    elif link_mode == "manual":
        if has_score or (assessment and (assessment.get("notes") or "").strip()):
            fulfillment = "met"
            detail_ar = "تقييم يدوي مسجّل."
        elif has_files:
            fulfillment = "partial"
            detail_ar = "مرفق دون تقييم يدوي كامل."
    else:
        if has_files:
            fulfillment = "met"
            detail_ar = f"{ev_count} مرفق/شاهد."
        elif has_survey and rule.get("evidence_category") == "survey":
            fulfillment = "partial"
            detail_ar = "نتائج استبيان متاحة — يُفضّل تسجيل شاهد."

    if not rule.get("is_required") and fulfillment == "missing":
        fulfillment = "not_applicable"
        detail_ar = "دليل داعم اختياري."

    return {
        "status": fulfillment,
        "status_label": FULFILLMENT_STATUS_LABELS.get(fulfillment, fulfillment),
        "detail_ar": detail_ar,
        "evidence_count": ev_count,
        "has_survey_data": has_survey,
        "is_bound": False,
        "binding_id": None,
    }


def build_indicator_evidence_coverage_map(
    conn,
    *,
    semester: str,
    department_id: int | None,
    catalog_version: str,
    assessments: dict[int, dict[str, Any]] | None = None,
    ev_counts: dict[int, int] | None = None,
) -> dict[int, dict[str, Any]]:
    """ملخص تغطية الأدلة لكل مؤشر — للعرض في تبويب الامتثال."""
    ensure_evidence_binding_schema(conn)
    cat_ver = resolve_catalog_version(conn, catalog_version)
    ensure_evidence_rules_for_catalog(conn, cat_ver)

    from backend.services.accreditation_evidence_bindings import list_bindings

    if ev_counts is None:
        ev_counts = evidence_counts_by_indicator(conn, semester, department_id)

    bindings = list_bindings(
        conn, semester=semester, department_id=department_id, indicator_id=None
    )

    # سياسة «ربط يدوي فقط»: التغطية = المصادر المربوطة فعلياً + الشواهد المرفوعة.
    # لا توجد قواعد إلزامية ولا تحقّق آلي من بيانات الاستبيانات.
    bindings_by_indicator: dict[int, int] = {}
    for b in bindings:
        iid = int(b.get("indicator_id") or 0)
        if iid:
            bindings_by_indicator[iid] = bindings_by_indicator.get(iid, 0) + 1

    indicator_ids = set(bindings_by_indicator.keys())
    indicator_ids |= {iid for iid, n in ev_counts.items() if n}

    out: dict[int, dict[str, Any]] = {}
    for iid in indicator_ids:
        manual_bound = bindings_by_indicator.get(iid, 0)
        ev_count = ev_counts.get(iid, 0)
        if manual_bound == 0 and ev_count == 0:
            continue

        parts: list[str] = []
        if manual_bound:
            parts.append(f"{manual_bound} مصدر مربوط")
        if ev_count:
            parts.append(f"{ev_count} شاهد مرفوع")

        out[iid] = {
            "bound": manual_bound,
            "evidence_count": ev_count,
            "label_ar": " · ".join(parts),
            "detail_ar": "ربط يدوي",
            "status": "ok",
        }
    return out


def build_evidence_matrix(
    conn,
    *,
    semester: str,
    department_id: int | None = None,
    catalog_version: str | None = None,
) -> dict[str, Any]:
    ensure_evidence_binding_schema(conn)
    cat_ver = resolve_catalog_version(conn, catalog_version)
    ensure_evidence_rules_for_catalog(conn, cat_ver)

    from backend.services.accreditation_evidence_bindings import list_bindings

    rules = list_evidence_rules(conn, catalog_version=cat_ver)
    ev_counts = evidence_counts_by_indicator(conn, semester, department_id)
    bindings = list_bindings(
        conn, semester=semester, department_id=department_id, indicator_id=None
    )
    binding_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    for b in bindings:
        iid = int(b.get("indicator_id") or 0)
        etid = int(b.get("evidence_type_id") or 0)
        if iid and etid:
            binding_by_key[(iid, etid)] = b

    cur = conn.cursor()
    dept_clause = "department_id IS NULL" if department_id is None else "department_id = ?"
    params: list[Any] = [semester]
    if department_id is not None:
        params.append(int(department_id))
    cur.execute(
        f"""
        SELECT indicator_id, score_percent, compliance_status, notes
        FROM accreditation_assessments
        WHERE semester = ? AND {dept_clause}
        """,
        tuple(params),
    )
    assessments = {
        int(r[0] if not hasattr(r, "keys") else r["indicator_id"]): _row_dict(
            r, ["indicator_id", "score_percent", "compliance_status", "notes"]
        )
        for r in (cur.fetchall() or [])
    }

    rows_out: list[dict[str, Any]] = []
    summary = {"total": 0, "met": 0, "partial": 0, "missing": 0, "not_applicable": 0, "required": 0}

    survey_codes: set[str] = set()
    for rule in rules:
        cfg = rule.get("config") or {}
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except json.JSONDecodeError:
                cfg = {}
        st = (cfg.get("survey_template") or "").strip()
        if st:
            survey_codes.add(st)
    aggregate_cache = _build_survey_aggregate_cache(
        conn, semester=semester, department_id=department_id, template_codes=survey_codes
    )

    for rule in rules:
        iid = int(rule["indicator_id"])
        etid = int(rule.get("evidence_type_id") or 0)
        ev_count = ev_counts.get(iid, 0)
        fulfillment = _evaluate_rule_fulfillment(
            conn,
            rule={**rule, "indicator_id": iid},
            semester=semester,
            department_id=department_id,
            ev_count=ev_count,
            assessment=assessments.get(iid),
            binding=binding_by_key.get((iid, etid)),
            aggregate_cache=aggregate_cache,
        )
        summary["total"] += 1
        if rule.get("is_required"):
            summary["required"] += 1
        st = fulfillment["status"]
        if st in summary:
            summary[st] += 1

        rows_out.append(
            {
                "rule_id": rule["id"],
                "indicator_id": iid,
                "indicator_code": rule.get("indicator_code"),
                "indicator_title_ar": rule.get("indicator_title_ar"),
                "indicator_seq": None,
                "standard_code": rule.get("standard_code"),
                "standard_title_ar": rule.get("standard_title_ar"),
                "domain_code": rule.get("domain_code"),
                "domain_label": rule.get("domain_label"),
                "evidence_type_id": rule.get("evidence_type_id"),
                "evidence_type_code": rule.get("evidence_type_code"),
                "evidence_type_title_ar": rule.get("evidence_type_title_ar"),
                "evidence_category": rule.get("evidence_category"),
                "evidence_category_label": rule.get("evidence_category_label"),
                "link_mode": rule.get("link_mode"),
                "link_mode_label": rule.get("link_mode_label"),
                "is_required": bool(rule.get("is_required")),
                "notes_ar": rule.get("notes_ar") or "",
                "fulfillment": fulfillment,
            }
        )

    req_rows = [r for r in rows_out if r["is_required"]]
    req_met = sum(1 for r in req_rows if r["fulfillment"]["status"] == "met")
    coverage = round(100.0 * req_met / len(req_rows), 1) if req_rows else 0.0

    return {
        "status": "ok",
        "catalog_version": cat_ver,
        "semester": semester,
        "department_id": department_id,
        "summary": {
            **summary,
            "required_met": req_met,
            "required_coverage_percent": coverage,
        },
        "rows": rows_out,
        "link_mode_labels": LINK_MODE_LABELS,
        "fulfillment_labels": FULFILLMENT_STATUS_LABELS,
    }


def save_evidence_rule(
    conn,
    payload: dict[str, Any],
    *,
    actor: str = "",
) -> dict[str, Any]:
    ensure_evidence_binding_schema(conn)
    cat_ver = (payload.get("catalog_version") or "").strip()
    if not cat_ver:
        raise ValueError("catalog_version مطلوب")

    indicator_id = payload.get("indicator_id")
    evidence_type_code = (payload.get("evidence_type_code") or "").strip()
    if not indicator_id or not evidence_type_code:
        raise ValueError("indicator_id و evidence_type_code مطلوبان")

    cur = conn.cursor()
    et_row = cur.execute(
        "SELECT id FROM accreditation_evidence_types WHERE code = ? AND COALESCE(is_active, 1) = 1",
        (evidence_type_code,),
    ).fetchone()
    if not et_row:
        raise ValueError(f"نوع دليل غير معروف: {evidence_type_code}")
    et_id = int(et_row[0] if not hasattr(et_row, "keys") else et_row["id"])

    ind_row = cur.execute(
        """
        SELECT i.id FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE i.id = ? AND s.catalog_version = ?
        """,
        (int(indicator_id), cat_ver),
    ).fetchone()
    if not ind_row:
        raise ValueError("المؤشر لا يطابق إصدار الكتالوج")

    link_mode = (payload.get("link_mode") or "evidence").strip().lower()
    if link_mode not in LINK_MODE_LABELS:
        raise ValueError("link_mode غير صالح")

    is_required = 1 if payload.get("is_required", True) else 0
    notes = (payload.get("notes_ar") or "").strip()[:2000]
    sort_order = int(payload.get("sort_order") or 0)
    weight = float(payload.get("weight_percent") or 0)
    config = payload.get("config") or {}
    cfg_json = json.dumps(config, ensure_ascii=False)
    now = datetime.datetime.utcnow().isoformat()
    rule_id = payload.get("id")

    pg = is_postgresql()
    if rule_id:
        cur.execute(
            """
            UPDATE accreditation_indicator_evidence_rules SET
                evidence_type_id = ?, link_mode = ?, is_required = ?,
                weight_percent = ?, config_json = ?, notes_ar = ?,
                sort_order = ?, updated_at = ?, updated_by = ?, is_active = 1
            WHERE id = ? AND catalog_version = ?
            """,
            (
                et_id,
                link_mode,
                is_required,
                weight,
                cfg_json,
                notes,
                sort_order,
                now,
                actor,
                int(rule_id),
                cat_ver,
            ),
        )
        if cur.rowcount == 0:
            raise ValueError("قاعدة الربط غير موجودة")
        conn.commit()
        return {"status": "ok", "id": int(rule_id), "updated": True}

    if pg:
        cur.execute(
            """
            INSERT INTO accreditation_indicator_evidence_rules
            (catalog_version, indicator_id, evidence_type_id, link_mode, is_required,
             weight_percent, config_json, notes_ar, sort_order, is_active, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT (catalog_version, indicator_id, evidence_type_id) DO UPDATE SET
                link_mode = EXCLUDED.link_mode,
                is_required = EXCLUDED.is_required,
                weight_percent = EXCLUDED.weight_percent,
                config_json = EXCLUDED.config_json,
                notes_ar = EXCLUDED.notes_ar,
                sort_order = EXCLUDED.sort_order,
                is_active = 1,
                updated_at = EXCLUDED.updated_at,
                updated_by = EXCLUDED.updated_by
            RETURNING id
            """,
            (
                cat_ver,
                int(indicator_id),
                et_id,
                link_mode,
                is_required,
                weight,
                cfg_json,
                notes,
                sort_order,
                now,
                actor,
            ),
        )
        row = cur.fetchone()
        new_id = int(row[0] if row else 0)
    else:
        cur.execute(
            """
            INSERT OR IGNORE INTO accreditation_indicator_evidence_rules
            (catalog_version, indicator_id, evidence_type_id, link_mode, is_required,
             weight_percent, config_json, notes_ar, sort_order, is_active, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                cat_ver,
                int(indicator_id),
                et_id,
                link_mode,
                is_required,
                weight,
                cfg_json,
                notes,
                sort_order,
                now,
                actor,
            ),
        )
        cur.execute(
            """
            SELECT id FROM accreditation_indicator_evidence_rules
            WHERE catalog_version = ? AND indicator_id = ? AND evidence_type_id = ?
            """,
            (cat_ver, int(indicator_id), et_id),
        )
        row = cur.fetchone()
        new_id = int(row[0] if row else cur.lastrowid or 0)
        cur.execute(
            """
            UPDATE accreditation_indicator_evidence_rules SET
                link_mode = ?, is_required = ?, weight_percent = ?,
                config_json = ?, notes_ar = ?, sort_order = ?,
                is_active = 1, updated_at = ?, updated_by = ?
            WHERE id = ?
            """,
            (link_mode, is_required, weight, cfg_json, notes, sort_order, now, actor, new_id),
        )
    conn.commit()
    return {"status": "ok", "id": new_id}


def deactivate_evidence_rule(conn, rule_id: int) -> bool:
    ensure_evidence_binding_schema(conn)
    cur = conn.cursor()
    cur.execute(
        "UPDATE accreditation_indicator_evidence_rules SET is_active = 0 WHERE id = ?",
        (int(rule_id),),
    )
    conn.commit()
    return cur.rowcount > 0


_VALID_EVIDENCE_CATEGORIES = frozenset(EVIDENCE_CATEGORY_LABELS.keys())


def list_catalog_indicators(conn, catalog_version: str | None = None) -> list[dict[str, Any]]:
    """مؤشرات الكتالوج لاختيارها عند إنشاء قاعدة ربط."""
    cat_ver = resolve_catalog_version(conn, catalog_version)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT i.id, i.code, i.title_ar, i.sort_order,
               s.code AS standard_code, s.title_ar AS standard_title_ar, s.domain_code
        FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE s.catalog_version = ? AND COALESCE(i.is_active, 1) = 1 AND COALESCE(s.is_active, 1) = 1
        ORDER BY s.domain_code, s.sort_order, i.sort_order, i.code
        """,
        (cat_ver,),
    )
    rows = cur.fetchall() or []
    keys = [d[0] for d in (cur.description or ())]
    out = []
    for r in rows:
        d = _row_dict(r, keys)
        d["domain_label"] = DOMAIN_LABELS.get(d.get("domain_code"), d.get("domain_code"))
        out.append(d)
    return out


def save_evidence_type(
    conn,
    payload: dict[str, Any],
    *,
    actor: str = "",
) -> dict[str, Any]:
    ensure_evidence_binding_schema(conn)
    code = (payload.get("code") or "").strip().lower()
    title_ar = (payload.get("title_ar") or "").strip()
    if not code or not title_ar:
        raise ValueError("code و title_ar مطلوبان")
    if not all(c.isalnum() or c == "_" for c in code):
        raise ValueError("رمز نوع الدليل: أحرف إنجليزية وأرقام وشرطة سفلية فقط")

    category = (payload.get("category") or "file").strip().lower()
    if category not in _VALID_EVIDENCE_CATEGORIES:
        raise ValueError("تصنيف نوع الدليل غير صالح")

    description_ar = (payload.get("description_ar") or "").strip()[:2000]
    source_module = (payload.get("source_module") or "").strip()[:120]
    source_ref = (payload.get("source_ref") or "").strip()[:120]
    sort_order = int(payload.get("sort_order") or 0)
    type_id = payload.get("id")
    cur = conn.cursor()

    if type_id:
        row = cur.execute(
            """
            SELECT id, code, is_system, is_editable FROM accreditation_evidence_types
            WHERE id = ? AND COALESCE(is_active, 1) = 1
            """,
            (int(type_id),),
        ).fetchone()
        if not row:
            raise ValueError("نوع الدليل غير موجود")
        rd = _row_dict(row, ["id", "code", "is_system", "is_editable"])
        if int(rd.get("is_system") or 0) == 1:
            code = str(rd.get("code") or "").strip().lower()
        cur.execute(
            """
            UPDATE accreditation_evidence_types SET
                title_ar = ?, description_ar = ?, category = ?,
                source_module = ?, source_ref = ?, sort_order = ?
            WHERE id = ?
            """,
            (title_ar, description_ar, category, source_module, source_ref, sort_order, int(type_id)),
        )
        conn.commit()
        return {"status": "ok", "id": int(type_id), "updated": True}

    existing = cur.execute(
        "SELECT id FROM accreditation_evidence_types WHERE code = ?",
        (code,),
    ).fetchone()
    if existing:
        raise ValueError(f"رمز نوع الدليل مستخدم مسبقاً: {code}")

    pg = is_postgresql()
    if pg:
        cur.execute(
            """
            INSERT INTO accreditation_evidence_types
            (code, title_ar, description_ar, category, source_module, source_ref,
             is_system, is_editable, sort_order, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?, 1)
            RETURNING id
            """,
            (code, title_ar, description_ar, category, source_module, source_ref, sort_order),
        )
        row = cur.fetchone()
        new_id = int(row[0] if row else 0)
    else:
        cur.execute(
            """
            INSERT INTO accreditation_evidence_types
            (code, title_ar, description_ar, category, source_module, source_ref,
             is_system, is_editable, sort_order, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?, 1)
            """,
            (code, title_ar, description_ar, category, source_module, source_ref, sort_order),
        )
        new_id = int(cur.lastrowid or 0)
    conn.commit()
    return {"status": "ok", "id": new_id}


def deactivate_evidence_type(conn, type_id: int) -> bool:
    ensure_evidence_binding_schema(conn)
    cur = conn.cursor()
    row = cur.execute(
        "SELECT is_system FROM accreditation_evidence_types WHERE id = ?",
        (int(type_id),),
    ).fetchone()
    if not row:
        return False
    if int(_row_dict(row, ["is_system"]).get("is_system") or 0) == 1:
        raise ValueError("لا يمكن حذف أنواع الأدلة النظامية — يمكن إيقاف قواعد الربط فقط")
    cur.execute(
        "UPDATE accreditation_evidence_types SET is_active = 0 WHERE id = ?",
        (int(type_id),),
    )
    conn.commit()
    return cur.rowcount > 0
