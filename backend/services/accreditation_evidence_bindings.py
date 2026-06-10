"""ربط أدلة الاعتماد الفعلية — المرحلة ب2–ب3."""

from __future__ import annotations

import datetime
import json
from typing import Any

from backend.core.accreditation_catalog import resolve_catalog_version
from backend.core.accreditation_evidence_types import SURVEY_TEMPLATE_TO_EVIDENCE_TYPE
from backend.database.database import is_postgresql, table_exists
from backend.services.accreditation_evidence import list_evidence
from backend.services.accreditation_evidence_matrix import (
    ensure_evidence_binding_schema,
    list_evidence_rules,
)

BINDING_KIND_LABELS = {
    "survey": "استبيان (من المنظومة)",
    "report": "تقرير نظام",
    "witness": "شاهد / مرفق",
    "manual": "تقييم يدوي",
}

_VALID_BINDING_KINDS = frozenset(BINDING_KIND_LABELS.keys())

_PG_BINDINGS_DDL = """
    CREATE TABLE IF NOT EXISTS accreditation_evidence_bindings (
        id BIGSERIAL PRIMARY KEY,
        semester TEXT NOT NULL,
        department_id BIGINT,
        indicator_id BIGINT NOT NULL,
        evidence_type_id BIGINT NOT NULL,
        rule_id BIGINT,
        binding_kind TEXT NOT NULL,
        source_ref TEXT NOT NULL DEFAULT '',
        label_ar TEXT DEFAULT '',
        notes_ar TEXT DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        created_by TEXT DEFAULT '',
        updated_by TEXT DEFAULT '',
        UNIQUE (semester, department_id, indicator_id, evidence_type_id),
        CONSTRAINT accred_bind_ind_fk FOREIGN KEY (indicator_id)
            REFERENCES accreditation_indicators(id) ON DELETE CASCADE,
        CONSTRAINT accred_bind_type_fk FOREIGN KEY (evidence_type_id)
            REFERENCES accreditation_evidence_types(id) ON DELETE CASCADE,
        CONSTRAINT accred_bind_rule_fk FOREIGN KEY (rule_id)
            REFERENCES accreditation_indicator_evidence_rules(id) ON DELETE SET NULL
    )
"""


def ensure_bindings_schema(conn) -> None:
    ensure_evidence_binding_schema(conn)
    if table_exists(conn, "accreditation_evidence_bindings"):
        return
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(_PG_BINDINGS_DDL)
    else:
        from backend.database.database import TABLES_SCHEMA

        ddl = TABLES_SCHEMA.get("accreditation_evidence_bindings")
        if ddl and hasattr(conn, "executescript"):
            conn.executescript(ddl)
        elif ddl:
            cur.execute(ddl)
    conn.commit()


def _row_dict(row, keys: list[str] | None = None) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    if keys:
        return {keys[i]: row[i] for i in range(min(len(keys), len(row)))}
    return {}


def _parse_source_ref(source_ref: str) -> tuple[str, str]:
    ref = (source_ref or "").strip()
    if ":" in ref:
        kind, payload = ref.split(":", 1)
        return kind.strip().lower(), payload.strip()
    return "", ref


def _format_source_ref(binding_kind: str, payload: str) -> str:
    kind = (binding_kind or "").strip().lower()
    pl = (payload or "").strip()
    if kind == "witness" and pl.isdigit():
        return f"witness:{pl}"
    if kind == "survey" and pl and not pl.startswith("survey:"):
        return f"survey:{pl}"
    if kind == "report" and pl and not pl.startswith("report:"):
        return f"report:{pl}"
    if kind == "manual":
        return pl or "manual:assessment"
    return pl or kind


def _survey_sources(
    conn,
    *,
    semester: str,
    department_id: int | None,
    preferred_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    from backend.services.multi_surveys import list_templates
    from backend.services.survey_accreditation import survey_template_aggregate

    out: list[dict[str, Any]] = []
    preferred = preferred_codes or set()
    for tpl in list_templates(conn, active_only=True):
        code = (tpl.get("code") or "").strip()
        if not code:
            continue
        agg = survey_template_aggregate(
            conn, code, semester=semester, department_id=department_id
        )
        item = {
            "binding_kind": "survey",
            "source_ref": f"survey:{code}",
            "template_code": code,
            "label_ar": tpl.get("title_ar") or code,
            "aggregated": bool(agg.get("aggregated")),
            "response_count": int(agg.get("response_count") or 0),
            "overall_score_percent": agg.get("overall_score_percent"),
            "detail_ar": agg.get("detail_ar") or "",
            "is_recommended": code in preferred,
        }
        if preferred and code not in preferred:
            if not item["aggregated"] and item["response_count"] <= 0:
                continue
        out.append(item)
    out.sort(key=lambda x: (not x.get("is_recommended"), x.get("label_ar") or ""))
    return out


def _report_sources(
    conn,
    *,
    semester: str,
    department_id: int | None,
    evidence_types: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for et in evidence_types:
        module = (et.get("source_module") or "").strip()
        ref = (et.get("source_ref") or "").strip()
        cat = (et.get("category") or "").strip()
        if cat not in ("report", "system", "policy", "minutes") and module not in (
            "course_closure",
            "college_identity",
            "department_policies",
            "accreditation_manual",
            "accreditation_metrics",
            "quality_metrics",
        ):
            continue
        key = module or ref or et.get("code") or ""
        if not key or key in seen:
            continue
        seen.add(key)
        label = et.get("title_ar") or key
        detail = ""
        available = False
        count = 0
        cur = conn.cursor()
        if module == "course_closure" and table_exists(conn, "course_closure_reports"):
            dept_clause = "1=1"
            params: list[Any] = [semester]
            if department_id is not None:
                dept_clause = "c.department_id = ?"
                params.append(int(department_id))
            try:
                row = cur.execute(
                    f"""
                    SELECT COUNT(*) FROM course_closure_reports c
                    WHERE c.semester = ? AND {dept_clause}
                    """,
                    tuple(params),
                ).fetchone()
                count = int(row[0] if row else 0)
                available = count > 0
                detail = f"{count} تقرير إقفال للفصل"
            except Exception:
                pass
        elif module == "college_identity":
            if table_exists(conn, "college_identity_profile"):
                row = cur.execute(
                    "SELECT COUNT(*) FROM college_identity_profile WHERE COALESCE(is_active,1)=1"
                ).fetchone()
                count = int(row[0] if row else 0)
                available = count > 0
                detail = "هوية الكلية معتمدة" if available else "لا توجد هوية معتمدة"
        elif module == "department_policies" and department_id is not None:
            if table_exists(conn, "department_policies"):
                row = cur.execute(
                    """
                    SELECT COUNT(*) FROM department_policies
                    WHERE department_id = ? AND status = 'approved'
                    """,
                    (int(department_id),),
                ).fetchone()
                count = int(row[0] if row else 0)
                available = count > 0
                detail = f"{count} سياسة معتمدة"
        elif module == "accreditation_manual":
            if table_exists(conn, "accreditation_manual_inputs"):
                dept_clause = "department_id IS NULL" if department_id is None else "department_id = ?"
                params = [semester]
                if department_id is not None:
                    params.append(int(department_id))
                row = cur.execute(
                    f"SELECT COUNT(*) FROM accreditation_manual_inputs WHERE semester = ? AND {dept_clause}",
                    tuple(params),
                ).fetchone()
                count = int(row[0] if row else 0)
                available = count > 0
                detail = "إدخالات يدوية مسجّلة" if available else "لا إدخالات يدوية"
        out.append(
            {
                "binding_kind": "report",
                "source_ref": f"report:{key}",
                "report_key": key,
                "label_ar": label,
                "available": available,
                "count": count,
                "detail_ar": detail,
                "evidence_type_code": et.get("code"),
            }
        )
    return out


def _witness_sources(
    conn,
    *,
    semester: str,
    department_id: int | None,
    indicator_id: int,
) -> list[dict[str, Any]]:
    items = list_evidence(
        conn, semester=semester, department_id=department_id, indicator_id=indicator_id
    )
    out = []
    for it in items:
        eid = int(it["id"])
        title = it.get("title_ar") or it.get("original_name") or f"شاهد #{eid}"
        out.append(
            {
                "binding_kind": "witness",
                "source_ref": f"witness:{eid}",
                "evidence_id": eid,
                "label_ar": title,
                "evidence_type": it.get("evidence_type"),
                "external_url": it.get("external_url") or "",
                "download_url": it.get("download_url") or "",
                "uploaded_at": it.get("uploaded_at"),
            }
        )
    return out


def _catalog_report_evidence_types(conn) -> list[dict[str, Any]]:
    """أنواع أدلة النظام/التقارير — للربط اليدوي دون قواعد كتالوج."""
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT code, title_ar, category, source_module, source_ref
        FROM accreditation_evidence_types
        WHERE COALESCE(is_active, 1) = 1
          AND category IN ('report', 'system', 'policy', 'minutes', 'metric')
        ORDER BY sort_order, id
        """
    ).fetchall() or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if hasattr(row, "keys"):
            out.append(
                {
                    "code": row["code"],
                    "title_ar": row["title_ar"],
                    "category": row["category"],
                    "source_module": row["source_module"],
                    "source_ref": row["source_ref"],
                }
            )
        else:
            out.append(
                {
                    "code": row[0],
                    "title_ar": row[1],
                    "category": row[2],
                    "source_module": row[3],
                    "source_ref": row[4],
                }
            )
    return out


def _resolve_evidence_type_id(conn, payload: dict[str, Any], binding_kind: str) -> int:
    et_raw = payload.get("evidence_type_id")
    if et_raw not in (None, "", 0):
        return int(et_raw)
    code = (payload.get("evidence_type_code") or "").strip()
    if not code and binding_kind == "survey":
        _, tpl = _parse_source_ref((payload.get("source_ref") or "").strip())
        tpl = tpl or (payload.get("template_code") or "").strip()
        if tpl:
            code = (SURVEY_TEMPLATE_TO_EVIDENCE_TYPE.get(tpl) or "").strip()
    if not code and binding_kind == "witness":
        code = "generic_file_upload"
    if not code:
        raise ValueError("evidence_type_id أو evidence_type_code مطلوب")
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id FROM accreditation_evidence_types WHERE code = ? AND COALESCE(is_active, 1) = 1",
        (code,),
    ).fetchone()
    if not row:
        raise ValueError("نوع الدليل غير معروف")
    return int(row[0] if not hasattr(row, "keys") else row["id"])


def build_bindable_sources(
    conn,
    *,
    indicator_id: int,
    semester: str,
    department_id: int | None = None,
    catalog_version: str | None = None,
    evidence_type_id: int | None = None,
) -> dict[str, Any]:
    ensure_bindings_schema(conn)
    cat_ver = resolve_catalog_version(conn, catalog_version)
    iid = int(indicator_id)
    rules = list_evidence_rules(conn, catalog_version=cat_ver, indicator_id=iid)
    if evidence_type_id is not None:
        etid = int(evidence_type_id)
        rules = [r for r in rules if int(r.get("evidence_type_id") or 0) == etid]

    preferred_surveys: set[str] = set()
    evidence_types_for_reports: list[dict[str, Any]] = []
    for r in rules:
        cfg = r.get("config") or {}
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except json.JSONDecodeError:
                cfg = {}
        tpl = (cfg.get("survey_template") or "").strip()
        if not tpl and (r.get("source_module") or "") == "multi_surveys":
            tpl = (r.get("source_ref") or "").strip()
        if tpl:
            preferred_surveys.add(tpl)
        evidence_types_for_reports.append(
            {
                "code": r.get("evidence_type_code"),
                "title_ar": r.get("evidence_type_title_ar"),
                "category": r.get("evidence_category"),
                "source_module": r.get("source_module"),
                "source_ref": r.get("source_ref"),
            }
        )

    surveys = _survey_sources(
        conn,
        semester=semester,
        department_id=department_id,
        preferred_codes=preferred_surveys or None,
    )
    report_types = evidence_types_for_reports or _catalog_report_evidence_types(conn)
    reports = _report_sources(
        conn,
        semester=semester,
        department_id=department_id,
        evidence_types=report_types,
    )
    witnesses = _witness_sources(
        conn, semester=semester, department_id=department_id, indicator_id=iid
    )

    bindings = list_bindings(
        conn,
        semester=semester,
        department_id=department_id,
        indicator_id=iid,
        evidence_type_id=evidence_type_id,
    )

    expected = []
    for r in rules:
        expected.append(
            {
                "rule_id": r.get("id"),
                "evidence_type_id": r.get("evidence_type_id"),
                "evidence_type_code": r.get("evidence_type_code"),
                "evidence_type_title_ar": r.get("evidence_type_title_ar"),
                "evidence_category": r.get("evidence_category"),
                "evidence_category_label": r.get("evidence_category_label"),
                "link_mode": r.get("link_mode"),
                "link_mode_label": r.get("link_mode_label"),
                "is_required": bool(r.get("is_required")),
                "current_binding": next(
                    (
                        b
                        for b in bindings
                        if int(b.get("evidence_type_id") or 0) == int(r.get("evidence_type_id") or 0)
                    ),
                    None,
                ),
            }
        )

    return {
        "status": "ok",
        "catalog_version": cat_ver,
        "semester": semester,
        "department_id": department_id,
        "indicator_id": iid,
        "freeform_mode": True,
        "expected_evidence": expected,
        "sources": {
            "surveys": surveys,
            "reports": reports,
            "witnesses": witnesses,
            "manual": [
                {
                    "binding_kind": "manual",
                    "source_ref": "manual:assessment",
                    "label_ar": "تقييم يدوي / ملاحظات المؤشر",
                    "detail_ar": "يُسجّل من زر «تقييم» في خريطة الامتثال",
                }
            ],
        },
        "bindings": bindings,
        "binding_kind_labels": BINDING_KIND_LABELS,
    }


def list_bindings(
    conn,
    *,
    semester: str,
    department_id: int | None = None,
    indicator_id: int | None = None,
    evidence_type_id: int | None = None,
) -> list[dict[str, Any]]:
    ensure_bindings_schema(conn)
    cur = conn.cursor()
    dept_clause = "b.department_id IS NULL" if department_id is None else "b.department_id = ?"
    params: list[Any] = [semester]
    if department_id is not None:
        params.append(int(department_id))
    extra = ""
    if indicator_id is not None:
        extra += " AND b.indicator_id = ?"
        params.append(int(indicator_id))
    if evidence_type_id is not None:
        extra += " AND b.evidence_type_id = ?"
        params.append(int(evidence_type_id))
    cur.execute(
        f"""
        SELECT b.id, b.semester, b.department_id, b.indicator_id, b.evidence_type_id,
               b.rule_id, b.binding_kind, b.source_ref, b.label_ar, b.notes_ar,
               b.created_at, b.updated_at, b.created_by, b.updated_by,
               t.code AS evidence_type_code, t.title_ar AS evidence_type_title_ar,
               i.code AS indicator_code
        FROM accreditation_evidence_bindings b
        INNER JOIN accreditation_evidence_types t ON t.id = b.evidence_type_id
        INNER JOIN accreditation_indicators i ON i.id = b.indicator_id
        WHERE b.semester = ? AND {dept_clause} AND COALESCE(b.is_active, 1) = 1 {extra}
        ORDER BY b.indicator_id, b.evidence_type_id, b.id
        """,
        tuple(params),
    )
    rows = cur.fetchall() or []
    keys = [d[0] for d in (cur.description or ())]
    out = []
    for r in rows:
        d = _row_dict(r, keys)
        d["binding_kind_label"] = BINDING_KIND_LABELS.get(
            d.get("binding_kind"), d.get("binding_kind")
        )
        out.append(d)
    return out


def save_binding(
    conn,
    payload: dict[str, Any],
    *,
    actor: str = "",
) -> dict[str, Any]:
    ensure_bindings_schema(conn)
    sem = (payload.get("semester") or "").strip()
    if not sem:
        raise ValueError("semester مطلوب")
    indicator_id = payload.get("indicator_id")
    if not indicator_id:
        raise ValueError("indicator_id مطلوب")

    binding_kind = (payload.get("binding_kind") or "").strip().lower()
    if binding_kind not in _VALID_BINDING_KINDS:
        raise ValueError("binding_kind غير صالح")

    evidence_type_id = _resolve_evidence_type_id(conn, payload, binding_kind)

    dept_raw = payload.get("department_id")
    department_id = int(dept_raw) if dept_raw not in (None, "", "null") else None

    source_ref = (payload.get("source_ref") or "").strip()
    if not source_ref:
        raise ValueError("source_ref مطلوب")

    kind_from_ref, payload_ref = _parse_source_ref(source_ref)
    if kind_from_ref and kind_from_ref != binding_kind:
        raise ValueError("source_ref لا يطابق binding_kind")
    source_ref = _format_source_ref(binding_kind, payload_ref or source_ref)

    if binding_kind == "witness":
        eid = payload_ref if payload_ref.isdigit() else source_ref.split(":")[-1]
        if not str(eid).isdigit():
            raise ValueError("معرّف الشاهد غير صالح")
        witnesses = list_evidence(
            conn,
            semester=sem,
            department_id=department_id,
            indicator_id=int(indicator_id),
        )
        if not any(int(w["id"]) == int(eid) for w in witnesses):
            raise ValueError("الشاهد غير موجود لهذا المؤشر")

    label_ar = (payload.get("label_ar") or "").strip()[:500]
    notes_ar = (payload.get("notes_ar") or "").strip()[:2000]
    rule_id = payload.get("rule_id")
    binding_id = payload.get("id")
    now = datetime.datetime.utcnow().isoformat()
    cur = conn.cursor()
    pg = is_postgresql()

    if binding_id:
        cur.execute(
            """
            UPDATE accreditation_evidence_bindings SET
                binding_kind = ?, source_ref = ?, label_ar = ?, notes_ar = ?,
                rule_id = ?, updated_at = ?, updated_by = ?, is_active = 1
            WHERE id = ? AND semester = ? AND indicator_id = ? AND evidence_type_id = ?
            """,
            (
                binding_kind,
                source_ref,
                label_ar,
                notes_ar,
                int(rule_id) if rule_id else None,
                now,
                actor,
                int(binding_id),
                sem,
                int(indicator_id),
                int(evidence_type_id),
            ),
        )
        if cur.rowcount == 0:
            raise ValueError("الربط غير موجود")
        conn.commit()
        return {"status": "ok", "id": int(binding_id), "updated": True}

    if pg:
        cur.execute(
            """
            INSERT INTO accreditation_evidence_bindings
            (semester, department_id, indicator_id, evidence_type_id, rule_id,
             binding_kind, source_ref, label_ar, notes_ar, is_active,
             created_at, updated_at, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT (semester, department_id, indicator_id, evidence_type_id) DO UPDATE SET
                rule_id = EXCLUDED.rule_id,
                binding_kind = EXCLUDED.binding_kind,
                source_ref = EXCLUDED.source_ref,
                label_ar = EXCLUDED.label_ar,
                notes_ar = EXCLUDED.notes_ar,
                is_active = 1,
                updated_at = EXCLUDED.updated_at,
                updated_by = EXCLUDED.updated_by
            RETURNING id
            """,
            (
                sem,
                department_id,
                int(indicator_id),
                int(evidence_type_id),
                int(rule_id) if rule_id else None,
                binding_kind,
                source_ref,
                label_ar,
                notes_ar,
                now,
                now,
                actor,
                actor,
            ),
        )
        row = cur.fetchone()
        new_id = int(row[0] if row else 0)
    else:
        cur.execute(
            """
            INSERT OR IGNORE INTO accreditation_evidence_bindings
            (semester, department_id, indicator_id, evidence_type_id, rule_id,
             binding_kind, source_ref, label_ar, notes_ar, is_active,
             created_at, updated_at, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                sem,
                department_id,
                int(indicator_id),
                int(evidence_type_id),
                int(rule_id) if rule_id else None,
                binding_kind,
                source_ref,
                label_ar,
                notes_ar,
                now,
                now,
                actor,
                actor,
            ),
        )
        cur.execute(
            """
            SELECT id FROM accreditation_evidence_bindings
            WHERE semester = ? AND indicator_id = ? AND evidence_type_id = ?
              AND ((department_id IS NULL AND ? IS NULL) OR department_id = ?)
            """,
            (
                sem,
                int(indicator_id),
                int(evidence_type_id),
                department_id,
                department_id,
            ),
        )
        row = cur.fetchone()
        new_id = int(row[0] if row else cur.lastrowid or 0)
        cur.execute(
            """
            UPDATE accreditation_evidence_bindings SET
                rule_id = ?, binding_kind = ?, source_ref = ?, label_ar = ?,
                notes_ar = ?, is_active = 1, updated_at = ?, updated_by = ?
            WHERE id = ?
            """,
            (
                int(rule_id) if rule_id else None,
                binding_kind,
                source_ref,
                label_ar,
                notes_ar,
                now,
                actor,
                new_id,
            ),
        )
    conn.commit()
    return {"status": "ok", "id": new_id}


def deactivate_binding(conn, binding_id: int) -> bool:
    ensure_bindings_schema(conn)
    cur = conn.cursor()
    cur.execute(
        "UPDATE accreditation_evidence_bindings SET is_active = 0 WHERE id = ?",
        (int(binding_id),),
    )
    conn.commit()
    return cur.rowcount > 0
